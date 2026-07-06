from src.api.auth import DEFAULT_BRAND_ID
from src.db.models import ProductPage
from src.services.page_visual_contract import normalize_visual, validate_visual


def test_page_api_returns_html_visual_payload(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    created = client.post(
        "/api/v1/projects",
        json={"name": "Visual contract", "brand_id": DEFAULT_BRAND_ID, "raw_input_text": "무선 사용"},
        headers=headers,
    )
    project_id = created.json()["id"]
    assert client.post(
        f"/api/v1/projects/{project_id}/page",
        json={"style_preset": "modern"},
        headers=headers,
    ).status_code == 201
    page = db_session.query(ProductPage).filter(ProductPage.project_id == project_id).one()
    section = page.sections[0]
    section.visual_kind = "html_graphic"
    section.visual_payload = {
        "layout_variant": "benefit_cards",
        "cards": [{"title": "간편한 이동", "body": "필요한 곳으로 옮겨 사용"}],
    }
    section.image_asset_id = None
    db_session.commit()

    response = client.get(
        f"/api/v1/projects/{project_id}/page",
        headers=headers,
    )
    assert response.status_code == 200
    item = response.json()["sections"][0]
    assert item["visual_kind"] == "html_graphic"
    assert item["visual_payload"]["layout_variant"] == "benefit_cards"


def test_html_graphic_is_complete_without_image_asset():
    visual = normalize_visual(
        section_type="comparison",
        image_asset_id=None,
        visual_kind="html_graphic",
        visual_payload={
            "layout_variant": "comparison_cards",
            "cards": [
                {"title": "기존 방식", "body": "전원 위치에 제약", "tone": "muted"},
                {"title": "무선 사용", "body": "필요한 장소로 이동", "tone": "positive"},
            ],
        },
    )
    assert validate_visual(visual) == []


def test_image_visual_requires_asset_id():
    visual = normalize_visual(
        section_type="hero",
        image_asset_id=None,
        visual_kind="image",
        visual_payload={"layout_variant": "hero_overlay"},
    )
    assert validate_visual(visual) == ["image_asset_required"]


def test_html_graphic_without_layout_is_defaulted():
    visual = normalize_visual(
        section_type="detail_1",
        image_asset_id=None,
        visual_kind="html_graphic",
        visual_payload={"cards": [{"title": "장점", "body": "편리함"}]},
    )
    assert visual["visual_payload"]["layout_variant"] == "benefit_cards"


def test_image_with_asset_id_is_valid():
    visual = normalize_visual(
        section_type="hero",
        image_asset_id="asset-123",
        visual_kind="image",
        visual_payload={"layout_variant": "hero_overlay"},
    )
    assert validate_visual(visual) == []


def test_invalid_html_layout_returns_error():
    visual = normalize_visual(
        section_type="comparison",
        image_asset_id=None,
        visual_kind="html_graphic",
        visual_payload={"layout_variant": "unknown_layout"},
    )
    errors = validate_visual(visual)
    assert "invalid_html_layout" in errors


def test_html_graphic_cards_required_for_benefit():
    visual = normalize_visual(
        section_type="detail_1",
        image_asset_id=None,
        visual_kind="html_graphic",
        visual_payload={"layout_variant": "benefit_cards"},
    )
    errors = validate_visual(visual)
    assert "html_cards_required" in errors


def test_spec_table_requires_rows():
    visual = normalize_visual(
        section_type="guarantee",
        image_asset_id=None,
        visual_kind="html_graphic",
        visual_payload={"layout_variant": "spec_table"},
    )
    errors = validate_visual(visual)
    assert "spec_rows_required" in errors


def test_invalid_visual_kind_returns_error():
    visual = normalize_visual(
        section_type="hero",
        image_asset_id=None,
        visual_kind="unknown_kind",
        visual_payload={},
    )
    errors = validate_visual(visual)
    assert "invalid_visual_kind" in errors
