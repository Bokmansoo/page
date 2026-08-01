from unittest.mock import patch

from io import BytesIO

from PIL import Image

from src.agents.nodes.image_generation.agent import ImageGenerationAgent
from src.agents.nodes.page_assembly.agent import PageAssemblyAgent
from src.agents.state import AgentRunState
from src.db.models import Asset, PageSection
from src.services.url_evidence_collector import URLEvidence


AUTH_HEADERS = {
    "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
    "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
}

def _high_resolution_png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (1200, 1200), color="white").save(buffer, format="PNG")
    return buffer.getvalue()


HIGH_RES_PNG = _high_resolution_png()


def test_uploaded_photo_is_preferred_and_second_photo_is_used_for_product_introduction():
    state = AgentRunState(
        project_id="project-1",
        outputs={
            "source_collection": {
                "uploaded_images": [
                    {
                        "asset_id": "upload-hero",
                        "filename": "product-main-front.jpg",
                        "source_type": "uploaded",
                    },
                    {
                        "asset_id": "upload-detail",
                        "filename": "product-detail.jpg",
                        "source_type": "uploaded",
                    },
                ],
                "url_images": [
                    {
                        "asset_id": "url-photo",
                        "filename": "product-url.jpg",
                        "source_type": "url-extracted",
                    }
                ],
            },
            "visual_planning": {
                "visual_slots": [
                    {"slot_id": "hero", "role": "representative_product"},
                    {"slot_id": "comparison", "role": "product_introduction"},
                ]
            },
        },
    )

    image_output = ImageGenerationAgent().run(state).outputs["image_generation"]

    assert image_output["candidates"]["hero"][0]["asset_id"] == "upload-hero"
    assert image_output["candidates"]["hero"][0]["is_recommended"] is True
    assert image_output["candidates"]["comparison"][1]["asset_id"] == "upload-detail"
    assert image_output["candidates"]["comparison"][1]["is_recommended"] is True
    assert all(
        candidate["source_type"] != "mock-generated"
        for candidates in image_output["candidates"].values()
        for candidate in candidates
    )
    assert image_output["jobs"][0]["status"] == "skipped_existing_product_image"


def test_missing_photo_returns_structured_photo_request_without_mock_asset():
    state = AgentRunState(
        project_id="project-1",
        outputs={
            "source_collection": {"uploaded_images": [], "url_images": []},
            "visual_planning": {"visual_slots": [{"slot_id": "hero", "role": "representative_product"}]},
        },
    )

    state = ImageGenerationAgent().run(state)
    image_output = state.outputs["image_generation"]
    candidate = image_output["candidates"]["hero"][0]

    assert candidate["asset_id"] is None
    assert candidate["source_type"] == "missing-image"
    assert candidate["label"] == "상품 사진을 추가해 주세요"
    assert image_output["images"] == []

    assembled = PageAssemblyAgent().run(state).outputs["page_assembly"]
    hero = assembled["sections"][0]
    assert hero["image_id"] is None
    assert hero["visual_slot"]["status"] == "missing_image"
    assert hero["visual_kind"] == "image"


def test_one_uploaded_photo_keeps_the_same_original_asset_id_when_reused():
    state = AgentRunState(
        project_id="project-1",
        outputs={
            "source_collection": {
                "uploaded_images": [
                    {
                        "asset_id": "original-photo",
                        "filename": "product-main.jpg",
                        "source_type": "uploaded",
                    }
                ],
                "url_images": [],
            },
            "visual_planning": {
                "visual_slots": [
                    {"slot_id": "hero", "role": "representative_product"},
                    {"slot_id": "comparison", "role": "product_introduction"},
                ]
            },
        },
    )

    state = ImageGenerationAgent().run(state)
    assembled = PageAssemblyAgent().run(state).outputs["page_assembly"]
    hero, introduction = assembled["sections"][:2]

    assert hero["visual_slot"]["asset_id"] == "original-photo"
    assert introduction["visual_slot"]["asset_id"] == "original-photo"
    assert hero["visual_kind"] == introduction["visual_kind"] == "image"


def test_uploaded_photo_is_served_and_linked_to_hero(client, db_session, tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    created = client.post(
        "/api/agent-runs",
        headers=AUTH_HEADERS,
        json={"product_name": "바디프랜드 미니 마사지건"},
    )
    assert created.status_code == 201
    project_id = created.json()["project_id"]

    uploaded = client.post(
        "/api/v1/files/upload",
        headers=AUTH_HEADERS,
        data={"project_id": project_id, "source_type": "uploaded"},
        files={"file": ("massage-gun-main.png", HIGH_RES_PNG, "image/png")},
    )
    assert uploaded.status_code == 201
    asset_id = uploaded.json()["id"]

    completed = client.post(
        f"/api/agent-runs/{created.json()['id']}/run-mock",
        headers=AUTH_HEADERS,
    )
    assert completed.status_code == 200
    hero = db_session.query(PageSection).filter(PageSection.section_type == "hero").one()
    assert hero.image_asset_id == asset_id

    served = client.get(f"/api/v1/files/assets/{asset_id}", headers=AUTH_HEADERS)
    assert served.status_code == 200
    assert served.content == HIGH_RES_PNG
    assert served.headers["content-type"] == "image/png"
    assert not any(
        candidate["source_type"] == "mock-generated"
        for candidates in completed.json()["outputs"]["image_generation"]["candidates"].values()
        for candidate in candidates
    )


def test_url_collected_photo_requires_selection_before_being_linked_to_hero(client, db_session):
    product_url = "https://shop.example.com/products/massage-gun"
    image_url = "https://cdn.example.com/massage-gun-main.jpg"

    def fake_collect(url, **_kwargs):
        return URLEvidence(url=url, title="미니 마사지건", image_urls=[image_url])

    with patch("src.api.agent_runs.collect_url_evidence", side_effect=fake_collect):
        created = client.post(
            "/api/agent-runs",
            headers=AUTH_HEADERS,
            json={"product_name": "", "product_url": product_url, "description": "판매자가 확인한 마사지 기능"},
        )

    assert created.status_code == 201
    run_id = created.json()["id"]
    asset = db_session.query(Asset).filter(Asset.project_id == created.json()["project_id"]).one()
    assert asset.source_type == "url-extracted"
    assert asset.file_path == image_url

    completed = client.post(f"/api/agent-runs/{run_id}/run-mock", headers=AUTH_HEADERS)
    assert completed.status_code == 200
    hero = (
        db_session.query(PageSection)
        .filter(PageSection.section_type == "hero")
        .one()
    )
    assert hero.image_asset_id is None
    assert hero.visual_payload["missing_state"] == "source_approval_required"
    assert completed.json()["outputs"]["image_generation"]["jobs"][0]["status"] == "awaiting_source_approval"

    rights_confirmed = client.patch(
        f"/api/v1/files/assets/{asset.id}/usage-status",
        headers=AUTH_HEADERS,
        json={"usage_status": "seller_owned"},
    )
    assert rights_confirmed.status_code == 200

    selected = client.patch(
        f"/api/v1/projects/{created.json()['project_id']}/page",
        headers=AUTH_HEADERS,
        json={
            "sections": [
                {
                    "id": hero.id,
                    "title": hero.title,
                    "body_copy": hero.body_copy,
                    "image_asset_id": asset.id,
                    "sort_order": hero.sort_order,
                    "is_visible": hero.is_visible,
                }
            ]
        },
    )
    assert selected.status_code == 200
    selected_hero = next(section for section in selected.json()["sections"] if section["id"] == hero.id)
    assert selected_hero["image_asset_id"] == asset.id
    assert "missing_state" not in (selected_hero["visual_payload"] or {})


def test_multiple_url_photos_wait_for_selection_and_apply_the_selected_main_photo():
    state = AgentRunState(
        project_id="project-1",
        outputs={
            "source_collection": {
                "uploaded_images": [],
                "url_images": [
                    {"asset_id": "url-detail", "filename": "product-detail.jpg", "source_type": "url-extracted"},
                    {"asset_id": "url-main", "filename": "product-main-front.jpg", "source_type": "url-extracted"},
                    {"asset_id": "url-side", "filename": "product-side.jpg", "source_type": "url-extracted"},
                ],
            },
            "visual_planning": {
                "visual_slots": [{"slot_id": "hero", "role": "representative_product"}]
            },
        },
    )

    state = ImageGenerationAgent().run(state)
    hero_candidates = state.outputs["image_generation"]["candidates"]["hero"]
    assert hero_candidates[0]["asset_id"] == "url-main"
    assert all(candidate["requires_approval"] is True for candidate in hero_candidates)
    assert not any(candidate["is_recommended"] for candidate in hero_candidates)
    assert state.outputs["image_generation"]["jobs"][0]["status"] == "awaiting_source_approval"

    unapproved_hero = PageAssemblyAgent().run(state).outputs["page_assembly"]["sections"][0]
    assert unapproved_hero["image_asset_id"] is None
    assert unapproved_hero["visual_slot"]["status"] == "awaiting_source_approval"

    state.selected_image_candidates["hero"] = hero_candidates[0]["candidate_id"]
    approved_hero = PageAssemblyAgent().run(state).outputs["page_assembly"]["sections"][0]
    assert approved_hero["image_asset_id"] == "url-main"


def test_uploaded_photo_added_after_url_collection_is_preferred_for_hero(
    client, db_session, tmp_path, monkeypatch
):
    """A user may add a better product photo after starting from a product URL."""
    from src.config import settings

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    product_url = "https://shop.example.com/products/massage-gun"
    image_url = "https://cdn.example.com/massage-gun-main.jpg"

    def fake_collect(url, **_kwargs):
        return URLEvidence(url=url, title="massage gun", image_urls=[image_url])

    with patch("src.api.agent_runs.collect_url_evidence", side_effect=fake_collect):
        created = client.post(
            "/api/agent-runs",
            headers=AUTH_HEADERS,
            json={"product_name": "massage gun", "product_url": product_url, "description": "판매자가 확인한 마사지 기능"},
        )

    assert created.status_code == 201
    uploaded = client.post(
        "/api/v1/files/upload",
        headers=AUTH_HEADERS,
        data={"project_id": created.json()["project_id"], "source_type": "uploaded"},
        files={"file": ("massage-gun-front.png", HIGH_RES_PNG, "image/png")},
    )
    assert uploaded.status_code == 201
    uploaded_asset_id = uploaded.json()["id"]
    url_asset_id = created.json()["product_input"]["asset_ids"][0]
    finalized = client.patch(
        f"/api/agent-runs/{created.json()['id']}/input-assets",
        headers=AUTH_HEADERS,
        json={"asset_ids": [uploaded_asset_id, url_asset_id]},
    )
    assert finalized.status_code == 200

    completed = client.post(
        f"/api/agent-runs/{created.json()['id']}/run-mock",
        headers=AUTH_HEADERS,
    )
    assert completed.status_code == 200
    hero = db_session.query(PageSection).filter(PageSection.section_type == "hero").one()
    assert hero.image_asset_id == uploaded_asset_id
    assert completed.json()["outputs"]["image_generation"]["candidates"]["hero"][0]["asset_id"] == uploaded_asset_id
