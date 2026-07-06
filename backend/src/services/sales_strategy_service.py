import re
from typing import List, Literal

from pydantic import BaseModel

from src.db.models import ProductProject


SALES_DIRECTION_TO_STYLE = {
    "persuasion": "problem_solution",
    "emotional": "lifestyle",
    "information": "spec_focused",
}

class ConfirmationCardRow(BaseModel):
    field_key: str
    field_label: str
    suggested_value: str
    confidence: str
    edit_options: List[str]

class DirectionVariant(BaseModel):
    key: str
    name: str
    is_recommended: bool
    headline: str
    reason: str
    section_flow: List[str]
    target: str
    recommended_visual_mood: str

class SalesStrategyResponse(BaseModel):
    target_customer: str
    buyer_problem: str
    main_selling_point: str
    supporting_points: List[str]
    tone: str
    price_strategy: str
    image_selection: List[str]
    risk_notes: List[str]
    confirmation_rows: List[ConfirmationCardRow]
    directions: List[DirectionVariant]


class SalesStrategyConfirmationRequest(BaseModel):
    target_customer: str
    buyer_problem: str
    main_selling_point: str
    supporting_points: List[str]
    tone: str
    price_strategy: str
    image_selection: List[str]
    risk_notes: List[str]
    selected_direction: Literal["persuasion", "emotional", "information"]


def map_sales_direction_to_style(direction: str) -> str:
    return SALES_DIRECTION_TO_STYLE[direction]


def _confirmed_understanding(project: ProductProject) -> dict:
    snapshot = project.intake_snapshot if isinstance(project.intake_snapshot, dict) else {}
    value = snapshot.get("confirmed_understanding", {})
    return value if isinstance(value, dict) else {}


def _understanding_field(understanding: dict, key: str) -> tuple[str, bool]:
    field = understanding.get(key, {})
    if not isinstance(field, dict):
        return "", True
    return str(field.get("value") or "").strip(), bool(field.get("is_suggestion", True))


def _list_field(understanding: dict, key: str) -> list[str]:
    value = understanding.get(key, [])
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _confirmed_fact_texts(project: ProductProject) -> list[str]:
    return [
        fact.fact_text.strip()
        for fact in (project.facts or [])
        if fact.verification_status == "confirmed" and fact.fact_text and fact.fact_text.strip()
    ]


def _extract_price_strategy(raw_text: str, confirmed_facts: list[str]) -> tuple[str, str]:
    pattern = re.compile(r"\d[\d,]*(?:원|만원|%)|할인|쿠폰|무료\s*배송|정가")
    for fact in confirmed_facts:
        if pattern.search(fact):
            return fact, "high"

    for sentence in re.split(r"[\n.!?]+", raw_text):
        sentence = sentence.strip()
        if sentence and pattern.search(sentence):
            return sentence, "medium"

    return "", "low"


def _classify_product(content: str) -> str:
    if any(key in content for key in ["아동", "유아", "키즈", "kids", "baby", "아기", "장난감", "어린이"]):
        return "kids"
    if any(key in content for key in ["매트", "테이블", "리빙", "식탁", "홈", "인테리어", "생활", "living", "home"]):
        return "home"
    if any(key in content for key in ["테크", "스마트폰", "전자기기", "충전기", "텀블러", "진공", "보온", "배터리", "tech", "device"]):
        return "tech"
    return "general"


def generate_sales_strategy(project: ProductProject, db) -> SalesStrategyResponse:
    understanding = _confirmed_understanding(project)
    product_type, product_type_is_suggestion = _understanding_field(understanding, "product_type")
    confirmed_target, target_is_suggestion = _understanding_field(understanding, "target_customer")
    confirmed_problem, _ = _understanding_field(understanding, "buyer_problem")
    tone_candidates = _list_field(understanding, "tone_candidates")
    unknowns = _list_field(understanding, "unknowns")
    confirmed_facts = _confirmed_fact_texts(project)

    raw_text = (project.raw_input_text or "").strip()
    content = f"{project.name or ''} {raw_text} {product_type} {' '.join(confirmed_facts)}".lower()
    product_kind = _classify_product(content)
    display_product = product_type or project.name or "상품"

    if confirmed_target:
        target_customer = confirmed_target
    elif product_kind == "kids":
        target_customer = "상품의 안전성과 사용 편의성을 꼼꼼히 확인하는 영유아 부모 및 보호자"
    elif product_kind == "home":
        target_customer = "주방 관리 편의성과 공간의 조화를 함께 고려하는 생활용품 구매자"
    elif product_kind == "tech":
        target_customer = "검증 가능한 성능과 사용 편의성을 비교하는 IT 기기 구매자"
    else:
        target_customer = "상품의 실제 장점과 가격 근거를 확인하고 구매하는 소비자"

    if confirmed_problem:
        buyer_problem = confirmed_problem
    elif product_kind == "kids":
        buyer_problem = "안전 관련 정보와 실제 사용 편의성을 구매 전에 판단하기 어려움"
    elif product_kind == "home":
        buyer_problem = "관리 방법과 공간 활용 효과를 구매 전에 구체적으로 판단하기 어려움"
    elif product_kind == "tech":
        buyer_problem = "표현된 성능이 실제 사용 조건에서도 유효한지 판단하기 어려움"
    else:
        buyer_problem = "상품의 차별점과 구매 근거를 한눈에 파악하기 어려움"

    if confirmed_facts:
        main_selling_point = confirmed_facts[0]
        supporting_points = confirmed_facts[1:4]
        selling_point_confidence = "high"
    elif product_kind == "kids":
        main_selling_point = f"{display_product}의 안전 정보와 사용 편의성을 이해하기 쉽게 제시"
        supporting_points = []
        selling_point_confidence = "medium"
    elif product_kind == "home":
        main_selling_point = f"{display_product}의 관리 편의성과 공간 활용 가치를 중심으로 제안"
        supporting_points = []
        selling_point_confidence = "medium"
    elif product_kind == "tech":
        main_selling_point = f"{display_product}의 검증 가능한 성능과 사용 편의성을 중심으로 제안"
        supporting_points = []
        selling_point_confidence = "medium"
    else:
        main_selling_point = f"{display_product}이 해결하는 구매 고민을 중심으로 실용적 가치를 제안"
        supporting_points = []
        selling_point_confidence = "medium"

    if tone_candidates:
        tone = tone_candidates[0]
    elif product_kind == "kids":
        tone = "따뜻하고 차분하게 안전 정보를 설명하는 톤"
    elif product_kind == "tech":
        tone = "검증된 정보를 간결하게 전달하는 전문적인 톤"
    else:
        tone = "부담 없이 이해할 수 있는 친근하고 신뢰감 있는 톤"

    price_strategy, price_confidence = _extract_price_strategy(raw_text, confirmed_facts)
    asset_filenames = [asset.filename for asset in (project.assets or [])]
    risk_notes = [f"확인 필요: {unknown}" for unknown in unknowns]
    if not confirmed_facts:
        risk_notes.append("인증, 시험 수치, 소재 비율은 확인된 근거가 있을 때만 상세페이지에 사용")

    target_confidence = "high" if confirmed_target and not target_is_suggestion else "medium"
    if not confirmed_target and not product_type_is_suggestion:
        target_confidence = "medium"
    price_value = price_strategy or "등록된 가격 전략 및 할인 정보가 없습니다. (수정 필요)"
    image_value = ", ".join(asset_filenames) if asset_filenames else "등록된 이미지 자산이 없습니다. 이미지를 첨부해주세요."
    confirmation_rows = [
        ConfirmationCardRow(
            field_key="target_customer",
            field_label="핵심 타겟 고객",
            suggested_value=target_customer,
            confidence=target_confidence,
            edit_options=[
                "기능과 가격을 비교하는 실용적인 구매자",
                "사용 편의성을 우선하는 초보 구매자",
                "검증된 정보를 꼼꼼히 확인하는 구매자",
            ],
        ),
        ConfirmationCardRow(
            field_key="main_selling_point",
            field_label="핵심 소구점",
            suggested_value=main_selling_point,
            confidence=selling_point_confidence,
            edit_options=[
                f"{display_product}의 가장 큰 사용 편의성을 중심으로 설명",
                f"{display_product}이 해결하는 구매 고민을 중심으로 설명",
                "확인된 소재와 성능 정보를 중심으로 설명",
            ],
        ),
        ConfirmationCardRow(
            field_key="tone",
            field_label="톤앤매너",
            suggested_value=tone,
            confidence="medium",
            edit_options=[
                "신뢰감을 주는 단정하고 정제된 어조",
                "친근하고 쉬운 대화체 어조",
                "기능과 근거를 간결하게 전달하는 전문적인 어조",
            ],
        ),
        ConfirmationCardRow(
            field_key="price_strategy",
            field_label="가격/할인 전략",
            suggested_value=price_value,
            confidence=price_confidence,
            edit_options=[
                "할인 없이 상품 가치와 정가를 중심으로 설명",
                "실제 운영 중인 할인 또는 쿠폰 정보를 직접 입력",
                "세트 구성과 배송 혜택이 있다면 직접 입력",
            ],
        ),
        ConfirmationCardRow(
            field_key="image_selection",
            field_label="대표 이미지 자산",
            suggested_value=image_value,
            confidence="high" if asset_filenames else "low",
            edit_options=asset_filenames,
        ),
    ]

    recommended_key = "persuasion"
    if project.category in {"Fashion", "Beauty"}:
        recommended_key = "emotional"
    elif project.category == "Food" or product_kind == "tech":
        recommended_key = "information"

    directions = [
        DirectionVariant(
            key="persuasion",
            name="설득형 (문제 해결형)",
            is_recommended=recommended_key == "persuasion",
            headline=f"{buyer_problem}, {display_product} 선택 기준부터 확인해보세요",
            reason="구매자의 고민을 먼저 짚고 확인된 상품 근거로 해결 방향을 설명합니다.",
            section_flow=["고객 고민", "핵심 해결 방향", "확인된 상품 근거", "사용 장점", "구매 전 확인사항"],
            target=target_customer,
            recommended_visual_mood="문제와 해결책의 대비가 분명한 정돈된 레이아웃과 신뢰감 있는 색상",
        ),
        DirectionVariant(
            key="emotional",
            name="감성형 (라이프스타일형)",
            is_recommended=recommended_key == "emotional",
            headline=f"일상 속 {display_product}, 사용 장면에서 느껴지는 가치를 보여드려요",
            reason="확인 가능한 사용 맥락과 이미지로 상품이 일상에 주는 변화를 전달합니다.",
            section_flow=["사용 전 고민", "대표 사용 장면", "일상의 변화", "확인된 상품 장점", "상품 정보"],
            target=target_customer,
            recommended_visual_mood="실제 사용 사진을 중심으로 한 자연스러운 채광과 편안한 생활 공간",
        ),
        DirectionVariant(
            key="information",
            name="정보형 (스펙 강조형)",
            is_recommended=recommended_key == "information",
            headline=f"{display_product}, 확인된 정보만 빠르게 비교해보세요",
            reason="검증된 사실과 아직 확인이 필요한 정보를 구분해 합리적인 구매 판단을 돕습니다.",
            section_flow=["핵심 정보 요약", "확인된 소재와 성능", "사용 및 관리 방법", "구성 정보", "미확인 정보 안내"],
            target=target_customer,
            recommended_visual_mood="표와 수치의 출처가 명확한 미니멀 레이아웃과 실제 상품 디테일 이미지",
        ),
    ]

    return SalesStrategyResponse(
        target_customer=target_customer,
        buyer_problem=buyer_problem,
        main_selling_point=main_selling_point,
        supporting_points=supporting_points,
        tone=tone,
        price_strategy=price_strategy or "N/A",
        image_selection=asset_filenames,
        risk_notes=risk_notes,
        confirmation_rows=confirmation_rows,
        directions=directions,
    )
