from src.services.commerce_cut_quality import inspect_commerce_cuts_quality


def test_inspect_commerce_cuts_quality():
    # 1. Prepare cuts with some issues
    # - Hero/problem cuts without image_asset_id should trigger warnings
    # - Excessive copy lengths should trigger warnings
    cuts = [
        {
            "section_type": "header",
            "layout_type": "hero_visual",
            "headline": "매우매우매우매우매우매우매우매우매우매우매우매우매우매우매우매우매우매우긴헤드라인", # 41자
            "subcopy": "짧은 카피",
            "supporting_text": None,
            "image_asset_id": None, # hero image missing warning
        },
        {
            "section_type": "product_information",
            "layout_type": "spec_visual",
            "headline": "스펙 정보",
            "subcopy": "짧은 본문",
            "supporting_text": None,
            "image_asset_id": None, # spec is not critical for image
        }
    ]

    warnings = inspect_commerce_cuts_quality(cuts)

    # We expect 2 warnings:
    # 1. Headline too long in header (>36 chars)
    # 2. Hero visual cut missing product_image
    assert len(warnings) == 2
    assert any("헤드라인" in w for w in warnings)
    assert any("제품" in w or "이미지" in w for w in warnings)
