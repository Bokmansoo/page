import pytest
from src.services.style_strategy_service import (
    get_category_frame,
    generate_style_candidates,
    is_valid_style_candidate_key,
)

def test_living_category_uses_problem_solution_frame():
    frame = get_category_frame("Living")

    assert [section.key for section in frame.sections] == [
        "problem_statement",
        "main_claim",
        "secondary_benefit",
        "main_claim_support",
        "benefit_list",
        "summary_claim",
        "product_information",
    ]
    assert frame.sections[0].label == "고객의 고민"
    assert frame.sections[-1].label == "상품 정보"

def test_fashion_category_uses_style_fit_frame():
    frame = get_category_frame("Fashion")

    assert [section.key for section in frame.sections] == [
        "style_context",
        "main_claim",
        "secondary_benefit",
        "main_claim_support",
        "benefit_list",
        "summary_claim",
        "product_information",
    ]
    assert frame.sections[0].label == "어떤 스타일에 어울릴까?"
    assert frame.sections[0].key == "style_context"

def test_beauty_category_uses_routine_frame():
    frame = get_category_frame("Beauty")

    assert [section.key for section in frame.sections] == [
        "skin_or_use_concern",
        "ingredient_or_texture",
        "secondary_benefit",
        "main_claim_support",
        "benefit_list",
        "summary_claim",
        "product_information",
    ]
    assert frame.sections[0].key == "skin_or_use_concern"
    assert frame.sections[1].key == "ingredient_or_texture"

def test_food_category_uses_notice_frame():
    frame = get_category_frame("Food")

    assert [section.key for section in frame.sections] == [
        "intake_or_eating_context",
        "ingredient_origin",
        "secondary_benefit",
        "main_claim_support",
        "benefit_list",
        "summary_claim",
        "product_information",
    ]
    assert frame.sections[0].key == "intake_or_eating_context"
    assert frame.sections[1].key == "ingredient_origin"

def test_generate_three_style_candidates_with_recommendation_and_channel_badges():
    candidates = generate_style_candidates(
        category="Living",
        product_title="루메나 휴대용 무선 냉각선풍기",
        confirmed_facts=[
            "4,800mAh 배터리",
            "최대 18시간 무선 사용",
            "휴대용 무선 냉각 선풍기",
        ],
    )

    assert len(candidates) == 3
    assert sum(1 for candidate in candidates if candidate.is_ai_recommended) == 1
    assert all(candidate.name for candidate in candidates)
    assert all(candidate.sales_strategy for candidate in candidates)
    assert all(candidate.preview_summary for candidate in candidates)
    assert all(candidate.channel_fit in {"coupang", "smartstore", "both"} for candidate in candidates)

def test_generate_candidates_feedback_adjusts_recommendation():
    # Test spec-focused feedback option
    candidates_spec = generate_style_candidates(
        category="Living",
        product_title="Test title",
        confirmed_facts=["fact 1"],
        feedback_option="더 스펙 중심으로"
    )
    rec_spec = [c for c in candidates_spec if c.is_ai_recommended]
    assert len(rec_spec) == 1
    assert rec_spec[0].key == "spec_focused"

    # Test lifestyle feedback option
    candidates_life = generate_style_candidates(
        category="Living",
        product_title="Test title",
        confirmed_facts=["fact 1"],
        feedback_option="더 감성적으로"
    )
    rec_life = [c for c in candidates_life if c.is_ai_recommended]
    assert len(rec_life) == 1
    assert rec_life[0].key == "lifestyle"


def test_style_candidate_key_validation():
    assert is_valid_style_candidate_key("problem_solution")
    assert is_valid_style_candidate_key("spec_focused")
    assert is_valid_style_candidate_key("lifestyle")
    assert not is_valid_style_candidate_key("unknown_style")
