from dataclasses import dataclass
from typing import List, Optional


STYLE_CANDIDATE_KEYS = {"problem_solution", "spec_focused", "lifestyle"}

@dataclass(frozen=True)
class DetailPageSectionFrame:
    key: str
    label: str
    description: str


@dataclass(frozen=True)
class CategoryDetailPageFrame:
    category: str
    strategy: str
    sections: List[DetailPageSectionFrame]


BASE_SECTIONS = [
    DetailPageSectionFrame("problem_statement", "고객의 고민", "고객이 실제로 겪는 불편과 구매 전 고민을 짚습니다."),
    DetailPageSectionFrame("main_claim", "핵심 해결 메시지", "이 상품이 핵심 문제를 어떻게 해결하는지 말합니다."),
    DetailPageSectionFrame("secondary_benefit", "추가 장점", "메인 메시지 외에 체감 가능한 보조 장점을 말합니다."),
    DetailPageSectionFrame("main_claim_support", "왜 이 상품이어야 할까?", "핵심 메시지를 근거 중심으로 한 번 더 보강합니다."),
    DetailPageSectionFrame("benefit_list", "구매 전 확인할 장점들", "나머지 장점을 보기 쉽게 정리합니다."),
    DetailPageSectionFrame("summary_claim", "한 문장 요약", "전체 흐름을 구매 판단 문장으로 요약합니다."),
    DetailPageSectionFrame("product_information", "상품 정보", "구매 전 확인해야 할 스펙, 구성품, 주의사항을 정리합니다."),
]


def get_category_frame(category: str) -> CategoryDetailPageFrame:
    normalized = (category or "General").strip().lower()

    if normalized in {"living", "life", "home", "생활", "리빙"}:
        return CategoryDetailPageFrame("Living", "problem_solution", BASE_SECTIONS)

    if normalized in {"fashion", "패션", "잡화", "fashion_accessory"}:
        sections = [
            DetailPageSectionFrame("style_context", "어떤 스타일에 어울릴까?", "착용/사용 장면과 스타일 맥락을 먼저 제시합니다."),
            *BASE_SECTIONS[1:],
        ]
        return CategoryDetailPageFrame("Fashion", "style_fit", sections)

    if normalized in {"beauty", "cosmetic", "뷰티", "화장품"}:
        sections = [
            DetailPageSectionFrame("skin_or_use_concern", "사용 전 고민", "피부/사용감/루틴 관련 고민을 먼저 제시합니다."),
            DetailPageSectionFrame("ingredient_or_texture", "성분과 사용감", "확인된 성분, 제형, 사용감을 근거 중심으로 정리합니다."),
            *BASE_SECTIONS[2:],
        ]
        return CategoryDetailPageFrame("Beauty", "concern_ingredient_routine", sections)

    if normalized in {"food", "health", "식품", "건강식품"}:
        sections = [
            DetailPageSectionFrame("intake_or_eating_context", "언제 먹으면 좋을까?", "섭취/식사용 상황을 제시합니다."),
            DetailPageSectionFrame("ingredient_origin", "원재료와 기준", "원재료, 함량, 원산지, 보관 기준을 정리합니다."),
            *BASE_SECTIONS[2:],
        ]
        return CategoryDetailPageFrame("Food", "ingredient_context_notice", sections)

    return CategoryDetailPageFrame("General", "problem_solution", BASE_SECTIONS)


@dataclass(frozen=True)
class StyleCandidate:
    key: str
    name: str
    is_ai_recommended: bool
    channel_fit: str
    sales_strategy: str
    design_direction: str
    preview_summary: str
    reason: str


def generate_style_candidates(
    category: str,
    product_title: str,
    confirmed_facts: List[str],
    feedback_option: Optional[str] = None,
) -> List[StyleCandidate]:
    facts_text = ", ".join(confirmed_facts[:3]) if confirmed_facts else "확인된 핵심 사실"
    title = product_title or "상품"

    # Default recommendations
    rec_key = "problem_solution"
    if feedback_option:
        normalized_feedback = feedback_option.strip()
        if normalized_feedback in {"더 스펙 중심으로", "더 짧고 강하게", "더 쿠팡스럽게"}:
            rec_key = "spec_focused"
        elif normalized_feedback in {"더 감성적으로", "더 스마트스토어스럽게"}:
            rec_key = "lifestyle"

    return [
        StyleCandidate(
            key="problem_solution",
            name="문제 해결형",
            is_ai_recommended=(rec_key == "problem_solution"),
            channel_fit="both",
            sales_strategy="고객의 불편을 먼저 짚고 상품의 핵심 해결 메시지로 설득합니다.",
            design_direction="선명한 제목, 강한 소구점, 모바일에서 빠르게 읽히는 구조",
            preview_summary=f"{title}의 핵심 고민을 제기한 뒤 {facts_text}을 근거로 해결 메시지를 강조합니다.",
            reason="생활/리빙 상품은 실제 사용 불편과 해결 기대가 구매 판단에 큰 영향을 줍니다.",
        ),
        StyleCandidate(
            key="spec_focused",
            name="스펙 강조형",
            is_ai_recommended=(rec_key == "spec_focused"),
            channel_fit="coupang",
            sales_strategy="수치, 기능, 구성 정보를 빠르게 비교할 수 있게 보여줍니다.",
            design_direction="스펙 카드, 숫자 강조, 짧은 문장 중심",
            preview_summary=f"{facts_text}처럼 비교 가능한 정보를 전면에 배치합니다.",
            reason="쿠팡 사용자는 빠른 비교와 즉시 구매 판단을 선호하는 경우가 많습니다.",
        ),
        StyleCandidate(
            key="lifestyle",
            name="라이프스타일형",
            is_ai_recommended=(rec_key == "lifestyle"),
            channel_fit="smartstore",
            sales_strategy="사용 장면과 감성적 효용을 보여줘 구매 상상을 돕습니다.",
            design_direction="이미지 중심, 부드러운 문구, 사용 장면 강조",
            preview_summary=f"{title}을 일상 공간에서 어떻게 쓰는지 상상할 수 있게 구성합니다.",
            reason="스마트스토어에서는 브랜드감과 사용 맥락이 상세페이지 체류에 도움이 됩니다.",
        ),
    ]


def is_valid_style_candidate_key(candidate_key: str) -> bool:
    return candidate_key in STYLE_CANDIDATE_KEYS or candidate_key in {"persuasion", "emotional", "information"}
