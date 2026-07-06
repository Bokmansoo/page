from src.services.image_asset_mapper import (
    classify_image_asset,
    find_missing_image_roles,
    map_image_assets_to_sections,
)


def test_map_image_assets_matches_correct_section_types():
    sections = [
        {"id": "sec-1", "section_type": "problem_statement"},
        {"id": "sec-2", "section_type": "main_claim"},
        {"id": "sec-3", "section_type": "product_information"},
    ]
    assets = [
        {
            "id": "asset-1",
            "filename": "lumena-main-product.jpg",
            "mime_type": "image/jpeg",
            "source_type": "uploaded",
        },
        {
            "id": "asset-2",
            "filename": "lumena-spec-chart.png",
            "mime_type": "image/png",
            "source_type": "uploaded",
        },
    ]

    assignments = map_image_assets_to_sections(sections, assets)

    # sec-1 (problem_statement) or sec-2 (main_claim) should get asset-1 (main)
    # sec-3 (product_information) should get asset-2 (spec)
    mapped_sec_1 = next((a for a in assignments if a["section_id"] == "sec-1"), None)
    mapped_sec_2 = next((a for a in assignments if a["section_id"] == "sec-2"), None)
    mapped_sec_3 = next((a for a in assignments if a["section_id"] == "sec-3"), None)

    assert (mapped_sec_1 and mapped_sec_1["asset_id"] == "asset-1") or (
        mapped_sec_2 and mapped_sec_2["asset_id"] == "asset-1"
    )
    assert mapped_sec_3 and mapped_sec_3["asset_id"] == "asset-2"


def test_map_image_assets_excludes_non_image_files():
    sections = [{"id": "sec-1", "section_type": "problem_statement"}]
    assets = [
        {
            "id": "asset-1",
            "filename": "document.pdf",
            "mime_type": "application/pdf",
            "source_type": "uploaded",
        }
    ]

    assignments = map_image_assets_to_sections(sections, assets)
    assert len(assignments) == 0


def test_map_image_assets_does_not_assign_zero_score_assets_to_unrelated_sections():
    sections = [{"id": "sec-1", "section_type": "product_information"}]
    assets = [
        {
            "id": "asset-1",
            "filename": "random-lifestyle.jpg",
            "mime_type": "image/jpeg",
            "source_type": "uploaded",
        }
    ]

    assignments = map_image_assets_to_sections(sections, assets)
    assert assignments == []


def test_map_image_assets_single_image_is_limited_to_priority_sections():
    sections = [
        {"id": "sec-1", "section_type": "problem_statement"},
        {"id": "sec-2", "section_type": "secondary_benefit"},
        {"id": "sec-3", "section_type": "benefit_list"},
        {"id": "sec-4", "section_type": "product_information"},
    ]
    assets = [
        {
            "id": "asset-1",
            "filename": "fan-main-product.jpg",
            "mime_type": "image/jpeg",
            "source_type": "uploaded",
        }
    ]

    assignments = map_image_assets_to_sections(sections, assets)

    assert [a["section_id"] for a in assignments] == ["sec-1"]


def test_classify_image_asset_uses_caption_and_korean_ocr_metadata():
    result = classify_image_asset(
        {
            "id": "asset-life",
            "filename": "IMG_1001.jpg",
            "mime_type": "image/jpeg",
            "source_type": "sourced",
            "metadata": {
                "caption": "거실에서 아이가 제품을 사용하는 생활 장면",
                "ocr_text": "어디서나 편리하게 사용",
            },
        }
    )

    assert result.primary_role == "lifestyle_scene"
    assert result.confidence >= 0.6
    assert "caption" in result.signals


def test_mapping_returns_role_confidence_and_respects_reuse_limit():
    sections = [
        {"id": "hero", "section_type": "main_claim"},
        {"id": "problem", "section_type": "problem_statement"},
        {"id": "benefit", "section_type": "secondary_benefit"},
        {"id": "features", "section_type": "benefit_list"},
        {"id": "info", "section_type": "product_information"},
    ]
    assets = [
        {
            "id": "main",
            "filename": "fan-main-product-front.png",
            "mime_type": "image/png",
            "source_type": "uploaded",
        },
        {
            "id": "life",
            "filename": "fan-lifestyle-use-scene.jpg",
            "mime_type": "image/jpeg",
            "source_type": "uploaded",
        },
        {
            "id": "detail",
            "filename": "fan-detail-feature-closeup.jpg",
            "mime_type": "image/jpeg",
            "source_type": "uploaded",
        },
        {
            "id": "package",
            "filename": "fan-package-components.jpg",
            "mime_type": "image/jpeg",
            "source_type": "uploaded",
        },
    ]

    assignments = map_image_assets_to_sections(sections, assets)

    assert len(assignments) >= 4
    assert all(item["asset_role"] for item in assignments)
    assert all(0.0 <= item["confidence"] <= 1.0 for item in assignments)
    assert max(
        sum(item["asset_id"] == asset["id"] for item in assignments)
        for asset in assets
    ) <= 2
    assert next(item for item in assignments if item["section_id"] == "info")[
        "asset_role"
    ] == "package_or_components"


def test_find_missing_image_roles_reports_unavailable_required_visuals():
    sections = [
        {"id": "problem", "section_type": "problem_statement"},
        {"id": "info", "section_type": "product_information"},
    ]
    assets = [
        {
            "id": "main",
            "filename": "fan-main-product.png",
            "mime_type": "image/png",
            "source_type": "uploaded",
        }
    ]

    assignments = map_image_assets_to_sections(sections, assets)
    missing = find_missing_image_roles(sections, assets, assignments)

    assert "lifestyle_scene" in missing
    assert "package_or_components" in missing
