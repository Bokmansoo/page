from unittest.mock import MagicMock

from src.services.figma_design_payload_builder import build_figma_design_payload


def _section(section_type: str, order: int, image_asset_id: str | None = None):
    section = MagicMock()
    section.id = f"sec-{order}"
    section.section_type = section_type
    section.title = f"Section {order}"
    section.body_copy = f"Section {order} body copy."
    section.sort_order = order
    section.is_visible = True
    section.image_asset_id = image_asset_id
    return section


def test_figma_payload_contains_visual_commerce_layout():
    project = MagicMock()
    project.id = "project-visual-payload"
    project.name = "루메나 휴대용 무선 냉각선풍기"
    project.category = "Living"
    project.selected_style = "problem_solution_living"
    project.selected_background = "cooling-blue"
    project.channel = "smartstore"
    project.brand = MagicMock()
    project.brand.name = "Sellform Brand"

    page = MagicMock()
    page.theme_color = "#5B7CFA"
    page.font_family = "Inter"
    page.sections = [
        _section("problem_statement", 0),
        _section("main_claim", 1, "asset-main"),
        _section("secondary_benefit", 2),
        _section("main_claim_support", 3),
        _section("benefit_list", 4),
        _section("summary_claim", 5),
        _section("product_information", 6),
    ]

    asset = MagicMock()
    asset.id = "asset-main"
    asset.filename = "fan.png"
    asset.file_path = "uploads/fan.png"
    asset.source_type = "uploaded"
    asset.mime_type = "image/png"
    asset.mime_type = "image/png"
    asset.source_type = "sourced"

    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [asset]
    db.query.return_value.filter.return_value.first.return_value = asset

    payload = build_figma_design_payload(
        project,
        page,
        db,
        public_asset_base_url="https://assets.sellform.example",
    )

    assert payload["schema_version"] == "1.0"
    assert payload["visual_layout"]["layout_version"] == "commerce_visual_v1"
    assert payload["visual_layout"]["width"] == 860
    assert len(payload["visual_layout"]["cuts"]) == 7
    assert payload["visual_layout"]["cuts"][0]["layout_type"] == "problem_visual"
    assert payload["visual_layout"]["cuts"][1]["image_asset_ref"] == "asset-main"
    assert payload["visual_layout"]["cuts"][1]["visual_slot"]["image_url"] == (
        "https://assets.sellform.example/uploads/fan.png"
    )
    assert payload["cuts"][1]["image_url"] == "https://assets.sellform.example/uploads/fan.png"
