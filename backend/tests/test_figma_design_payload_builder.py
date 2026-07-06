import pytest
from unittest.mock import MagicMock
from src.services.figma_design_payload_builder import build_figma_design_payload


def test_build_figma_design_payload():
    # 1. Prepare Mock models
    mock_project = MagicMock()
    mock_project.id = "proj-123"
    mock_project.name = "루메나 무선 선풍기"
    mock_project.category = "Living"
    mock_project.selected_style = "problem_solution_living"
    mock_project.brand = MagicMock(name="brand")
    mock_project.brand.name = "Lumena"

    mock_page = MagicMock()
    mock_page.id = "page-456"
    mock_page.project_id = "proj-123"
    mock_page.theme_color = "#5B7CFA"
    mock_page.font_family = "Sans-Serif"
    mock_page.project = mock_project

    # Mock sections
    mock_sec1 = MagicMock()
    mock_sec1.id = "sec-1"
    mock_sec1.section_type = "header"
    mock_sec1.title = "헤더 타이틀"
    mock_sec1.body_copy = "설명 문장 하나. 설명 문장 둘."
    mock_sec1.image_asset_id = "asset-999"
    mock_sec1.sort_order = 1
    mock_sec1.is_visible = True

    mock_sec2 = MagicMock()
    mock_sec2.id = "sec-2"
    mock_sec2.section_type = "product_information"
    mock_sec2.title = "스펙표"
    mock_sec2.body_copy = "스펙 정보 본문"
    mock_sec2.image_asset_id = None
    mock_sec2.sort_order = 2
    mock_sec2.is_visible = True

    mock_page.sections = [mock_sec1, mock_sec2]

    # Mock DB Session
    mock_db = MagicMock()
    
    # Mock Asset lookup
    mock_asset = MagicMock()
    mock_asset.id = "asset-999"
    mock_asset.filename = "wind_hero.png"
    mock_asset.file_path = "uploads/wind_hero.png"
    mock_asset.source_type = "uploaded"
    mock_asset.mime_type = "image/png"
    
    # Session query mocks
    mock_query = mock_db.query.return_value
    mock_filter = mock_query.filter.return_value
    mock_filter.all.return_value = [mock_asset]
    mock_filter.first.return_value = mock_asset

    # 2. Build payload
    payload = build_figma_design_payload(
        mock_project,
        mock_page,
        mock_db,
        public_asset_base_url="https://assets.sellform.example",
    )

    # 3. Assertions
    assert payload["schema_version"] == "1.0"
    assert payload["project"]["id"] == "proj-123"
    assert payload["project"]["name"] == "루메나 무선 선풍기"
    assert payload["project"]["category"] == "Living"

    assert payload["brand"]["primary_color"] == "#5B7CFA"
    assert payload["brand"]["font_family"] == "Sans-Serif"
    assert payload["brand"]["name"] == "Lumena"

    assert payload["page"]["canvas_width"] == 860
    assert payload["page"]["style_key"] == "problem_solution_living"

    assert len(payload["cuts"]) == 2
    
    # First cut assertions
    cut1 = payload["cuts"][0]
    assert cut1["section_id"] == "sec-1"
    assert cut1["section_type"] == "header"
    assert cut1["layout_type"] == "hero_visual"
    assert cut1["headline"] == "헤더 타이틀"
    # commerce visual cut sentence splitting
    assert "설명 문장 하나" in cut1["subcopy"]
    assert "설명 문장 둘" in cut1["supporting_text"]
    assert cut1["image_url"] == "https://assets.sellform.example/uploads/wind_hero.png"

    # Second cut assertions
    cut2 = payload["cuts"][1]
    assert cut2["section_id"] == "sec-2"
    assert cut2["layout_type"] == "spec_visual"
    assert cut2["image_url"] is None
