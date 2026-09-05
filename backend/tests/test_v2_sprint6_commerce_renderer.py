from types import SimpleNamespace

from src.services.commerce_renderer_service import build_commerce_artifact
from src.services.page_finalization_service import build_final_page_snapshot
from src.db.models import Brand, PageSection, ProductPage, ProductProject, User, Workspace


def _page(*sections):
    return SimpleNamespace(
        theme_color="#0f766e",
        font_family="Pretendard",
        sections=list(sections),
    )


def _section(section_id, section_type, order, **overrides):
    base = {
        "id": section_id,
        "section_type": section_type,
        "title": section_type,
        "body_copy": "확인된 설명",
        "associated_fact_ids": ["fact-1"],
        "image_asset_id": None,
        "visual_kind": "html_graphic",
        "visual_payload": {"layout_variant": "image_text"},
        "sort_order": order,
        "is_visible": True,
        "facts_stale": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_artifact_is_deterministic_and_keeps_final_specs_last():
    page = _page(
        _section("hero", "hero", 1),
        _section("spec", "specifications", 9),
    )
    first = build_commerce_artifact(page)
    second = build_commerce_artifact(page)

    assert first["ready"] is True
    assert first["artifact_hash"] == second["artifact_hash"]
    assert [section["id"] for section in first["sections"]] == ["hero", "spec"]
    assert first["renderer_rules"]["editor_ui_excluded"] is True
    assert first["template_tokens"]["canvas_width"] == 760


def test_template_candidates_have_distinct_renderer_tokens_and_warn_on_long_title():
    page = _page(
        _section("hero", "hero", 0, title="긴 한국어 제목 " * 12),
        _section("spec", "specifications", 1),
    )
    soft = build_commerce_artifact(page, template_key="commerce_story_soft")
    bold = build_commerce_artifact(page, template_key="commerce_story_bold")

    assert soft["template_tokens"]["section_gap"] != bold["template_tokens"]["section_gap"]
    assert any(warning["code"] == "title_wrap_review" for warning in soft["warnings"])


def test_artifact_blocks_supplier_capture_and_repeated_visuals():
    page = _page(
        _section("hero", "hero", 0, image_asset_id="supplier", visual_kind="image"),
        _section("feature", "features", 1, image_asset_id="supplier", visual_kind="image"),
        _section("spec", "specifications", 2),
    )
    supplier = SimpleNamespace(id="supplier", source_type="sourced", usage_status="reference_only")
    artifact = build_commerce_artifact(page, [supplier])
    codes = {issue["code"] for issue in artifact["blockers"]}

    assert artifact["ready"] is False
    assert "supplier_reference_not_renderable" in codes
    assert "repeated_visual" in codes


def test_artifact_blocks_unlinked_numbers_stale_facts_and_specs_out_of_order():
    page = _page(
        _section("spec", "specifications", 0),
        _section("after", "cta", 1, body_copy="10분 안에 사용하세요.", associated_fact_ids=[], facts_stale=True),
    )
    artifact = build_commerce_artifact(page)
    codes = {issue["code"] for issue in artifact["blockers"]}

    assert {"final_specification_not_last", "ungrounded_numeric_copy", "stale_fact"}.issubset(codes)


def test_hidden_sections_do_not_change_final_output_or_duplicate_detection():
    page = _page(
        _section("hero", "hero", 0, image_asset_id="generated", visual_kind="image"),
        _section("hidden", "features", 1, image_asset_id="generated", visual_kind="image", is_visible=False),
        _section("spec", "specifications", 2),
    )
    asset = SimpleNamespace(id="generated", source_type="ai_generated", usage_status="ai_generated")
    artifact = build_commerce_artifact(page, [asset])

    assert artifact["ready"] is True
    assert not any(issue["code"] == "repeated_visual" for issue in artifact["blockers"])


def test_artifact_api_exposes_same_renderer_contract(client, db_session):
    user = User(id="s6-user", email="s6@example.com", name="Sprint 6")
    workspace = Workspace(id="s6-workspace", name="Sprint 6", owner_id=user.id)
    brand = Brand(id="s6-brand", workspace_id=workspace.id, name="Brand")
    project = ProductProject(id="s6-project", workspace_id=workspace.id, brand_id=brand.id, name="Renderer")
    page = ProductPage(id="s6-page", project_id=project.id)
    db_session.add_all([user, workspace, brand, project, page])
    db_session.flush()
    db_session.add_all([
        # HTML blocks need no final image and make this focused API contract test deterministic.
        PageSection(
            id="s6-hero", page_id=page.id, section_type="hero", title="Hero", body_copy="설명",
            associated_fact_ids=["f1"], visual_kind="html_graphic", visual_payload={"layout_variant": "image_text"}, sort_order=0,
        ),
        PageSection(
            id="s6-spec", page_id=page.id, section_type="specifications", title="사양", body_copy="설명",
            associated_fact_ids=["f1"], visual_kind="html_graphic", visual_payload={"layout_variant": "image_text"}, sort_order=1,
        ),
    ])
    db_session.commit()

    response = client.get(
        "/api/v1/projects/s6-project/page/commerce-artifact",
        headers={"X-Mock-User-Id": "s6-user", "X-Mock-Workspace-Id": "s6-workspace"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_version"] == "commerce-renderer-v1"
    assert payload["renderer_rules"]["editor_ui_excluded"] is True


def test_final_snapshot_freezes_the_commerce_renderer_contract(db_session):
    page = _page(
        _section("hero", "hero", 0, visual_kind="html_graphic", visual_payload={"html": "<div>hero</div>"}),
        _section("specifications", "specifications", 1, associated_fact_ids=["fact-1"]),
    )
    page.project_id = "missing-project"
    page.project = None
    snapshot = build_final_page_snapshot(db_session, page)

    renderer = snapshot["commerce_renderer"]
    assert renderer["artifact_version"] == "commerce-renderer-v1"
    assert renderer["sections"][-1]["section_type"] == "specifications"
    assert renderer["renderer_rules"]["supplier_reference_output_forbidden"] is True


def test_version_snapshot_endpoint_supports_editor_comparison(client, db_session):
    user = User(id="s6-compare-user", email="compare@example.com", name="Sprint 6")
    workspace = Workspace(id="s6-compare-workspace", name="Sprint 6", owner_id=user.id)
    brand = Brand(id="s6-compare-brand", workspace_id=workspace.id, name="Brand")
    project = ProductProject(id="s6-compare-project", workspace_id=workspace.id, brand_id=brand.id, name="Renderer")
    page = ProductPage(id="s6-compare-page", project_id=project.id)
    db_session.add_all([user, workspace, brand, project, page])
    db_session.flush()
    from src.services.page_version_service import create_page_version
    version = create_page_version(
        project.id,
        "comparison",
        {"theme_color": "#0f766e", "font_family": "Pretendard", "sections": []},
        "commerce_story",
        db_session,
    )

    response = client.get(
        f"/api/v1/projects/{project.id}/page/versions/{version.id}",
        headers={"X-Mock-User-Id": user.id, "X-Mock-Workspace-Id": workspace.id},
    )

    assert response.status_code == 200
    assert response.json()["sections_json"]["font_family"] == "Pretendard"
