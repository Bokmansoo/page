from src.services.visual_page_renderer import build_visual_sections


def test_build_visual_sections_with_commerce_cuts():
    sections = [
        {
            "id": "sec-1",
            "section_type": "problem_statement",
            "title": "여름철 더위",
            "body_copy": "너무 더워요.",
            "image_asset_id": "asset-1",
        }
    ]

    image_assets = [
        {
            "id": "asset-1",
            "filename": "fan-lifestyle.jpg",
            "file_path": "uploads/fan-lifestyle.jpg",
            "mime_type": "image/jpeg",
        }
    ]

    result = build_visual_sections(
        product_name="루메나 선풍기",
        category="Living",
        sections=sections,
        selected_background="cooling-blue",
        image_assets=image_assets,
        use_commerce_cut=True,
    )

    assert len(result) == 1
    cut_section = result[0]
    
    # Verify cut-centric fields
    assert cut_section["layout"] == "problem_visual"
    assert cut_section["visual_slot"]["kind"] == "product_image"
    assert cut_section["visual_slot"]["asset_id"] == "asset-1"
    assert cut_section["headline"] == "여름철 더위"


def test_commerce_cut_visual_sections_include_selected_style_token():
    sections = [
        {
            "id": "sec-1",
            "section_type": "problem_statement",
            "title": "Warm lifestyle",
            "body_copy": "Lifestyle-led copy.",
            "image_asset_id": None,
        }
    ]

    result = build_visual_sections(
        product_name="Style product",
        category="Living",
        sections=sections,
        selected_background="cooling-blue",
        image_assets=[],
        use_commerce_cut=True,
        selected_style="lifestyle",
    )

    assert result[0]["style"]["style_key"] == "lifestyle"
    assert result[0]["style"]["background_tone"] == "warm_neutral"
