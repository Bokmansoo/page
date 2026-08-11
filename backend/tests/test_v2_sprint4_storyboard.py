from copy import deepcopy

import pytest

from src.db.models import Asset, Brand, FactEvidence, ProductFact, ProductProject, User, Workspace
from src.services.fact_evidence_service import mark_fact_dependents_stale
from src.services.storyboard_service import (
    StoryboardValidationError,
    generate_storyboard,
    mark_storyboard_assets_stale,
    validate_storyboard,
)


HEADERS = {"X-Mock-User-Id": "storyboard-user", "X-Mock-Workspace-Id": "storyboard-workspace"}


def _setup(db_session, *, name="YL-T02 마사지 베개", category="생활가전"):
    user = User(id=HEADERS["X-Mock-User-Id"], email="storyboard@example.com", name="Storyboard")
    workspace = Workspace(id=HEADERS["X-Mock-Workspace-Id"], name="Storyboard", owner_id=user.id)
    brand = Brand(id="storyboard-brand", workspace_id=workspace.id, name="Storyboard brand")
    project = ProductProject(id="storyboard-project", workspace_id=workspace.id, brand_id=brand.id, name=name, category=category)
    fact = ProductFact(id="storyboard-fact", project_id=project.id, fact_text="배터리 용량: 2000mAh", verification_status="seller_confirmed", needs_review=False, field_key="battery_capacity", normalized_value="2000", normalized_unit="mAh")
    evidence = FactEvidence(fact_id=fact.id, source_type="seller_input", original_text="배터리 용량 2000mAh")
    reference = Asset(id="storyboard-reference", project_id=project.id, source_type="sourced", usage_status="reference_only", filename="supplier.jpg", file_path="/tmp/supplier.jpg", mime_type="image/jpeg", file_size=10, asset_role="product_main")
    db_session.add_all([user, workspace, brand, project, fact, evidence, reference])
    db_session.commit()
    return project, user, fact, reference


def _final_asset(project_id: str):
    return Asset(id="storyboard-owned", project_id=project_id, source_type="uploaded", usage_status="seller_owned", filename="owned.jpg", file_path="/tmp/owned.jpg", mime_type="image/jpeg", file_size=10, asset_role="product_main")


def _mock_ai_asset(project_id: str):
    return Asset(
        id="storyboard-mock-ai",
        project_id=project_id,
        source_type="ai_generated",
        usage_status="ai_generated",
        filename="ai_planning-placeholder.png",
        file_path="/tmp/ai_planning-placeholder.png",
        mime_type="image/png",
        file_size=1900,
        width=512,
        height=512,
        quality_status="warning",
        quality_warnings=["LOW_RESOLUTION"],
        asset_role="product_main",
    )


def _real_ai_asset(project_id: str):
    return Asset(
        id="storyboard-real-ai",
        project_id=project_id,
        source_type="ai_generated",
        usage_status="ai_generated",
        filename="ai_product_scene.png",
        file_path="/tmp/ai_product_scene.png",
        mime_type="image/png",
        file_size=150_000,
        width=1024,
        height=1024,
        quality_status="usable",
        asset_role="product_main",
    )


@pytest.mark.parametrize("name,category", [
    ("YL-T02 목·어깨 마사지 베개", "생활가전"),
    ("자작나무 수분 크림", "뷰티"),
    ("밀폐용기 세트", "생활용품"),
])
def test_three_baseline_categories_create_grounded_seven_plus_section_storyboards(db_session, name, category):
    project, user, fact, reference = _setup(db_session, name=name, category=category)
    draft = generate_storyboard(project, [fact], [reference], db_session, user.id)
    assert 7 <= len([card for card in draft["cards"] if card["is_enabled"]]) <= 12
    assert all(set(card["source_fact_ids"]).issubset({fact.id}) for card in draft["cards"])
    assert draft["cards"][-1]["type"] in {"specifications", "final_specifications", "product_specifications"}
    assert any(card["scene_request"] for card in draft["cards"] if card["image_requirement"] == "ai_redesign_required")


def test_recommendations_build_three_candidates_and_never_assign_reference_asset(db_session):
    project, user, fact, reference = _setup(db_session)
    draft = generate_storyboard(project, [fact], [reference], db_session, user.id)

    assert draft["storyboard_version"] == 1
    assert {item["key"] for item in draft["recommendations"]} == {"safe_information", "visual_story", "balanced_sales"}
    assert 7 <= len(draft["cards"]) <= 12
    assert draft["cards"][-1]["type"] in {"specifications", "final_specifications", "product_specifications"}
    hero = next(card for card in draft["cards"] if card["type"] == "hero")
    assert hero["image_requirement"] == "ai_redesign_required"
    assert hero["image_asset_id"] is None
    assert reference.id in hero["candidate_asset_ids"]
    assert hero["scene_request"]


def test_mock_ai_placeholders_do_not_hide_required_sprint5_scenes(db_session):
    project, user, fact, reference = _setup(db_session)
    mock_asset = _mock_ai_asset(project.id)
    db_session.add(mock_asset)
    db_session.commit()

    draft = generate_storyboard(project, [fact], [reference, mock_asset], db_session, user.id)

    assert draft["selected_candidate_key"] == "safe_information"
    assert all(
        card.get("image_asset_id") != mock_asset.id
        for recommendation in draft["recommendations"]
        for card in recommendation["cards"]
    )
    assert all(recommendation["missing_images"] for recommendation in draft["recommendations"])
    hero = next(card for card in draft["cards"] if card["type"] == "hero")
    assert hero["image_requirement"] == "ai_redesign_required"


def test_real_ai_visual_remains_storyboard_ready(db_session):
    project, user, fact, reference = _setup(db_session)
    generated = _real_ai_asset(project.id)
    db_session.add(generated)
    db_session.commit()

    draft = generate_storyboard(project, [fact], [reference, generated], db_session, user.id)

    hero = next(card for card in draft["cards"] if card["type"] == "hero")
    assert hero["image_requirement"] == "asset_ready"
    assert hero["image_asset_id"] == generated.id


def test_validation_rejects_reference_duplicate_unknown_fact_and_final_spec_order(db_session):
    project, user, fact, reference = _setup(db_session)
    owned = _final_asset(project.id)
    mock_asset = _mock_ai_asset(project.id)
    db_session.add_all([owned, mock_asset]); db_session.commit()
    draft = generate_storyboard(project, [fact], [owned, reference], db_session, user.id)
    ids = {fact.id}

    duplicate = deepcopy(draft)
    duplicate["cards"] = [
        {"id": "hero", "type": "hero", "source_fact_ids": [fact.id], "image_asset_id": owned.id, "is_enabled": True},
        {"id": "spec", "type": "specifications", "source_fact_ids": [fact.id], "image_asset_id": owned.id, "is_enabled": True},
    ]
    try:
        validate_storyboard(duplicate, [owned, reference], ids)
        assert False, "duplicate final asset must be rejected"
    except StoryboardValidationError as exc:
        assert "repeated" in str(exc)

    reference_only = deepcopy(draft)
    next(card for card in reference_only["cards"] if card["type"] == "hero")["image_asset_id"] = reference.id
    try:
        validate_storyboard(reference_only, [owned, reference], ids)
        assert False, "reference-only final assignment must be rejected"
    except StoryboardValidationError as exc:
        assert "Reference-only" in str(exc)

    mock_placeholder = deepcopy(draft)
    next(card for card in mock_placeholder["cards"] if card["type"] == "hero")["image_asset_id"] = mock_asset.id
    try:
        validate_storyboard(mock_placeholder, [owned, reference, mock_asset], ids)
        assert False, "mock AI placeholder must be rejected"
    except StoryboardValidationError as exc:
        assert "mock placeholder" in str(exc)

    unknown_fact = deepcopy(draft)
    unknown_fact["cards"][0]["source_fact_ids"] = ["not-confirmed"]
    try:
        validate_storyboard(unknown_fact, [owned, reference], ids)
        assert False, "unknown fact must be rejected"
    except StoryboardValidationError as exc:
        assert "confirmed facts" in str(exc)

    wrong_order = deepcopy(draft)
    wrong_order["cards"] = [wrong_order["cards"][-1], *wrong_order["cards"][:-1]]
    try:
        validate_storyboard(wrong_order, [owned, reference], ids)
        assert False, "final specifications must remain last"
    except StoryboardValidationError as exc:
        assert "last" in str(exc)


def test_storyboard_endpoints_select_approve_and_fact_asset_changes_mark_stale(client, db_session):
    project, user, fact, reference = _setup(db_session)
    created = client.post(f"/api/v1/projects/{project.id}/storyboard/recommendations", headers=HEADERS)
    assert created.status_code == 200
    body = created.json()
    assert len(body["recommendations"]) == 3

    selected = client.post(f"/api/v1/projects/{project.id}/storyboard/select", headers=HEADERS, json={"candidate_key": "visual_story"})
    assert selected.status_code == 200
    assert selected.json()["selected_candidate_key"] == "visual_story"
    assert selected.json()["revision"] == 2

    restored = client.post(f"/api/v1/projects/{project.id}/storyboard/restore", headers=HEADERS, json={"revision": 1})
    assert restored.status_code == 200
    assert restored.json()["selected_candidate_key"] == "safe_information"
    assert restored.json()["revision"] == 3

    approved = client.post(f"/api/v1/projects/{project.id}/storyboard/approve", headers=HEADERS)
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["fact_snapshot_id"]

    mark_fact_dependents_stale(db_session, project.id, [fact.id])
    db_session.commit(); db_session.refresh(project)
    assert project.planning_draft["status"] == "stale"
    assert any(card["facts_stale"] for card in project.planning_draft["cards"] if fact.id in card.get("source_fact_ids", []))

    project.planning_draft["status"] = "approved"
    project.planning_draft["cards"][0]["candidate_asset_ids"] = [reference.id]
    assert mark_storyboard_assets_stale(project, [reference.id]) is True
    assert project.planning_draft["status"] == "stale"
