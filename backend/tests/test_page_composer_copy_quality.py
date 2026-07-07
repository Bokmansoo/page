import pytest
from src.services.page_generator import PageGenerationService
from src.services.copy_quality_guard import CopyQualityGuard

def test_page_generator_mock_no_forbidden_phrases():
    service = PageGenerationService(api_key=None)
    facts = [
        {
            "id": "fact-1",
            "fact_text": "원터치 간편 세척 가습기, 4L 대용량 수조",
            "source_text": "상품설명",
        }
    ]

    page = service.generate_page(
        category="Living",
        confirmed_facts=facts,
        style_preset="problem_solution",
        narrative_template="problem_solution",
    )

    forbidden_patterns = [
        "정리합니다", "보여주세요", "입력 정보를 바탕으로", "안전한 표현",
        "[AI 수정됨]", "+", "—", "최고", "완벽", "무조건",
        "핵심 사용 가치", "생활 패턴", "초보 구매자", "기존 대안",
        "또렷하게 정리해요", "포인트로 압축합니다", "체크할 항목을 정리",
        "줄이는 역할을 합니다", "분리해 보여줍니다"
    ]

    for section in page.sections:
        title = section.title
        body = section.body_copy

        # 모든 섹션 타이틀과 본문에 금지 문구가 없어야 한다
        for pattern in forbidden_patterns:
            assert pattern not in title, f"Section title '{title}' contains forbidden pattern '{pattern}'"
            assert pattern not in body, f"Section body '{body}' contains forbidden pattern '{pattern}'"

def test_copy_quality_guard_rules():
    # 금지 문구 정제 검증
    guard = CopyQualityGuard()
    
    # 금지 특수기호 및 AI 마커 정제 테스트
    cleaned_title = guard.clean_text("선풍기 + 에어컨 — [AI 수정됨] 시원함")
    assert "+" not in cleaned_title
    assert "—" not in cleaned_title
    assert "[AI 수정됨]" not in cleaned_title

    # 과장된 표현 포함 시 안전한 기본 문구로 교체 또는 정제
    is_valid, reason = guard.validate_text("최고의 가습기 완벽한 무조건 추천")
    assert not is_valid
    assert reason == "exaggeration"

    # 빈약한 제목 검증
    is_valid_title, title_reason = guard.validate_title("선풍")
    assert not is_valid_title
    assert title_reason == "too_short"


def test_copy_quality_guard_default_copy_is_also_valid():
    guard = CopyQualityGuard()

    section_types = [
        "hero",
        "target_customer",
        "problem_situation",
        "features",
        "lifestyle_scene",
        "comparison",
        "pre_purchase",
        "specifications",
        "caution",
        "cta",
    ]

    for section_type in section_types:
        default_copy = guard.get_default_copy(section_type, "루메나 휴대용 무선 냉각선풍기")

        is_valid_title, title_reason = guard.validate_title(default_copy["title"])
        assert is_valid_title, f"{section_type} default title failed: {title_reason} / {default_copy['title']}"

        for bullet in default_copy["bullets"]:
            is_valid_bullet, bullet_reason = guard.validate_text(bullet)
            assert is_valid_bullet, f"{section_type} default bullet failed: {bullet_reason} / {bullet}"


def test_problem_solution_mock_copy_uses_product_facts_not_internal_guide_text():
    service = PageGenerationService(api_key=None)
    facts = [
        {
            "id": "fact-1",
            "fact_text": "루메나 휴대용 무선 냉각선풍기는 콘센트 없이 책상, 차량, 야외에서 사용할 수 있는 휴대용 선풍기입니다.",
            "source_text": "manual_text",
        },
        {
            "id": "fact-2",
            "fact_text": "냉각 모드와 바람을 함께 사용해 더운 순간에 바로 시원함을 더합니다.",
            "source_text": "manual_text",
        },
    ]

    page = service.generate_page(
        category="Living",
        confirmed_facts=facts,
        style_preset="problem_solution",
        narrative_template="problem_solution",
    )

    combined_copy = " ".join(
        [section.title + " " + section.body_copy for section in page.sections]
    )

    for required_word in ["루메나", "무선", "냉각", "콘센트"]:
        assert required_word in combined_copy

    for forbidden_guide_text in [
        "확인된 상품 정보를 기준",
        "상품 사실로 정리합니다",
        "사용 환경에서 확인할 정보",
        "구매 전에 확인할 정보",
    ]:
        assert forbidden_guide_text not in combined_copy
