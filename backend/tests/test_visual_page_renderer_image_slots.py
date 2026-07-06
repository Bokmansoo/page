from src.services.visual_page_renderer import build_visual_sections


def test_build_visual_sections_maps_image_assets():
    sections = [
        {
            "key": "main_claim",
            "title": "일상의 불편을 덜어주는 실용적인 선택",
            "body": "본문 설명 문구",
            "image_asset_id": "asset-1",
        }
    ]

    image_assets = [
        {
            "id": "asset-1",
            "filename": "fan-hero.jpg",
            "file_path": "uploads/fan-hero.jpg",
            "mime_type": "image/jpeg",
        }
    ]

    result = build_visual_sections(
        product_name="루메나 휴대용 무선 냉각선풍기",
        category="Living",
        sections=sections,
        selected_background="cooling-blue",
        image_assets=image_assets,
    )

    slot = result[0]["visual_slot"]
    assert slot["kind"] == "product_image"
    assert slot["asset_id"] == "asset-1"
    assert slot["filename"] == "fan-hero.jpg"
    assert slot["file_path"] == "uploads/fan-hero.jpg"


def test_build_visual_sections_uses_background_when_section_has_no_image_mapping():
    sections = [
        {
            "key": "main_claim",
            "title": "일상의 불편을 덜어주는 실용적인 선택",
            "body": "본문 설명 문구",
            "image_asset_id": None,
        }
    ]

    image_assets = [
        {
            "id": "asset-1",
            "filename": "fan-hero.jpg",
            "file_path": "uploads/fan-hero.jpg",
            "mime_type": "image/jpeg",
        }
    ]

    result = build_visual_sections(
        product_name="루메나 휴대용 무선 냉각선풍기",
        category="Living",
        sections=sections,
        selected_background="cooling-blue",
        image_assets=image_assets,
    )

    slot = result[0]["visual_slot"]
    assert slot["kind"] == "generated_background"
    assert "asset_id" not in slot
