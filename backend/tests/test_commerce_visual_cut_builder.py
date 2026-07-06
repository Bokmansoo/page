from src.services.commerce_visual_cut_builder import build_commerce_visual_cuts, CommerceVisualCut


def test_build_commerce_visual_cuts_mapping():
    # 1. Setup mock page data
    page = {
        "id": "page-1",
        "theme_color": "#3B82F6",
        "font_family": "sans-serif",
        "sections": [
            {
                "id": "sec-1",
                "section_type": "problem_statement",
                "title": "여름철 더위로 고통받는 우리 가족",
                "body_copy": "매년 여름만 되면 치솟는 온도 때문에 방 안에서도 숨쉬기조차 힘듭니다. 에어컨을 켜자니 누진세 폭탄이 두렵고, 선풍기로는 역부족인 이 현실을 타개할 솔루션이 시급합니다.",
                "image_asset_id": "asset-1",
            },
            {
                "id": "sec-2",
                "section_type": "product_information",
                "title": "제품 스펙 정보",
                "body_copy": "모델명: LUMENA-FAN-V1\nKC 인증: JH07821-23001\n소비전력: 5W",
                "image_asset_id": None,
            }
        ]
    }

    assets = [
        {
            "id": "asset-1",
            "filename": "fan-lifestyle.jpg",
            "file_path": "uploads/fan-lifestyle.jpg",
            "mime_type": "image/jpeg",
        }
    ]

    project = {
        "id": "proj-1",
        "selected_background": "cooling-blue",
    }

    cuts = build_commerce_visual_cuts(page, assets, project)

    assert len(cuts) == 2
    
    # Check problem cut mapping
    prob_cut = cuts[0]
    assert isinstance(prob_cut, CommerceVisualCut)
    assert prob_cut.layout_type == "problem_visual"
    assert prob_cut.visual_role == "problem_scene"
    assert prob_cut.image_asset_id == "asset-1"
    assert "여름철 더위" in prob_cut.headline
    assert len(prob_cut.headline) <= 36
    assert len(prob_cut.subcopy) <= 90

    # Check spec cut mapping
    spec_cut = cuts[1]
    assert spec_cut.layout_type == "spec_visual"
    assert spec_cut.visual_role == "cutout_product"


def test_standard_sections_receive_valid_visual_roles():
    from src.services.image_generation_contract import VISUAL_ROLES
    
    sections = [
        {"id": "s1", "section_type": "header", "title": "t", "body": "b"},
        {"id": "s2", "section_type": "problem_statement", "title": "t", "body": "b"},
        {"id": "s3", "section_type": "main_claim", "title": "t", "body": "b"},
        {"id": "s4", "section_type": "main_claim_support", "title": "t", "body": "b"},
        {"id": "s5", "section_type": "benefit_list", "title": "t", "body": "b"},
        {"id": "s6", "section_type": "product_information", "title": "t", "body": "b"},
        {"id": "s7", "section_type": "summary_claim", "title": "t", "body": "b"},
        {"id": "s8", "section_type": "features", "title": "t", "body": "b"},
        {"id": "s9", "section_type": "specifications", "title": "t", "body": "b"},
        {"id": "s10", "section_type": "faq", "title": "t", "body": "b"},
    ]
    page = {"id": "page-2", "sections": sections}
    project = {"id": "proj-2", "selected_background": "minimal-white"}
    
    cuts = build_commerce_visual_cuts(page, [], project)
    
    assert len(cuts) == len(sections)
    for cut in cuts:
        assert cut.visual_role in VISUAL_ROLES, f"Role '{cut.visual_role}' for section '{cut.section_type}' is not a valid visual role"

