import json
import logging
import uuid
from typing import Any, Dict, List

import anthropic
from sqlalchemy.orm import Session

from src.config import settings
from src.db.models import ProductFact, ProductProject
from src.services.page_composer_service import PageComposerService
from src.services.copy_quality_guard import CopyQualityGuard

logger = logging.getLogger(__name__)

CARD_METADATA: Dict[str, Dict[str, str]] = {
    "hero": {"label": "히어로 메시지", "visual_strategy": "image_overlay"},
    "target_customer": {"label": "타깃 고객", "visual_strategy": "text_only"},
    "problem_situation": {"label": "문제 상황", "visual_strategy": "lifestyle_image"},
    "features": {"label": "특장점", "visual_strategy": "graphic_chart"},
    "lifestyle_scene": {"label": "사용 장면", "visual_strategy": "lifestyle_image"},
    "comparison": {"label": "비교 포인트", "visual_strategy": "graphic_chart"},
    "pre_purchase": {"label": "구매 전 확인사항", "visual_strategy": "text_only"},
    "specifications": {"label": "구성품/스펙", "visual_strategy": "text_only"},
    "caution": {"label": "주의사항", "visual_strategy": "text_only"},
    "cta": {"label": "최종 CTA", "visual_strategy": "image_overlay"},
}

CARD_ORDER = list(CARD_METADATA.keys())


class PlanningDraftService:
    @staticmethod
    def generate_draft(
        project: ProductProject,
        confirmed_facts: List[ProductFact],
        db: Session,  # kept for API compatibility and future persistence hooks
    ) -> Dict[str, Any]:
        api_key = settings.ANTHROPIC_API_KEY
        is_mock = not api_key or settings.FACTORY_RAG_RUNTIME_MOCK

        # 1. Normalize facts using PageComposerService
        normalized_data = PageComposerService.normalize_facts(project, confirmed_facts)

        # 2. Generate initial draft
        if is_mock:
            logger.info("Generating deterministic planning draft fallback.")
            draft = PlanningDraftService._generate_mock_draft(project, normalized_data)
        else:
            try:
                client = anthropic.Anthropic(api_key=api_key)
                logger.info("Generating planning draft via Claude.")
                draft = PlanningDraftService._generate_llm_draft(project, normalized_data, client)
            except Exception as exc:
                logger.error("Failed to generate planning draft via Claude. Falling back to deterministic draft: %s", exc)
                draft = PlanningDraftService._generate_mock_draft(project, normalized_data)

        # 3. Apply CopyQualityGuard to clean and validate output
        guard = CopyQualityGuard()
        for card in draft.get("cards", []):
            card["title"] = guard.clean_text(card.get("title", ""))
            card["bullets"] = [guard.clean_text(b) for b in card.get("bullets", [])]

            # Validate title
            is_valid_title, title_reason = guard.validate_title(card["title"])
            if not is_valid_title:
                card["title"] = guard.get_default_copy(card["type"], project.name or "상품")["title"]

            # Validate bullets
            validated_bullets = []
            for b in card["bullets"]:
                is_valid_b, b_reason = guard.validate_text(b)
                if is_valid_b:
                    validated_bullets.append(b)

            # Fallback if all bullets are invalid or empty
            if not validated_bullets:
                validated_bullets = guard.get_default_copy(card["type"], project.name or "상품")["bullets"]
            card["bullets"] = validated_bullets

        return draft

    @staticmethod
    def _generate_mock_draft(project: ProductProject, normalized_data: Dict[str, Any]) -> Dict[str, Any]:
        product_name = project.name or "상품"
        product_facts = normalized_data.get("product_facts") or []
        fact_ids = [f["id"] for f in product_facts]
        fact_texts = [f["text"] for f in product_facts]
        evidence_hint = fact_texts[0] if fact_texts else (project.raw_input_text or "")[:80]

        raw_cards = [
            (
                "hero",
                f"{product_name}, 필요한 순간 바로 쓰는 편리한 선택",
                [
                    f"{evidence_hint}",
                    "언제 어디서나 일상의 편리함을 한층 더 높여 줍니다."
                ],
                fact_ids[:1],
            ),
            (
                "target_customer",
                f"이런 분들께 {product_name}를 적극 추천해 드려요",
                [
                    "간편한 사용 방식과 실용성을 가장 중요하게 생각하시는 분",
                    "기존 제품들의 번거로움에 지쳐 새로운 대안을 찾고 계셨던 분"
                ],
                fact_ids[1:2],
            ),
            (
                "problem_situation",
                "매일 겪는 사소한 번거로움, 해결할 방법이 없을까 고민하셨나요?",
                [
                    "작고 사소한 불편함들이 쌓이다 보면 일상이 조금씩 번거로워집니다.",
                    "이제는 더 이상 미루지 말고 편리한 사용 경험으로 바꿔보세요."
                ],
                fact_ids[2:3],
            ),
            (
                "features",
                "사용자를 깊이 배려한 이 제품만의 핵심 강점",
                [
                    "누구나 쉽게 적응하고 직관적으로 사용할 수 있는 설계 구조",
                    "품질 기준을 거쳐 더욱 안심하고 오랫동안 사용할 수 있습니다."
                ],
                fact_ids[3:4],
            ),
            (
                "lifestyle_scene",
                "당신의 소중한 공간 어디에나 자연스럽게 어울리는 일상",
                [
                    "집, 사무실 등 사용 목적에 맞추어 어디서든 빛을 발합니다.",
                    "감각적이고 미니멀한 디자인으로 공간의 분위기를 한층 돋보이게 합니다."
                ],
                fact_ids[4:5],
            ),
            (
                "comparison",
                "비슷해 보이는 다른 제품들과의 차별점을 확인해 보세요",
                [
                    "기능의 기본에 충실하면서도 사용의 편의성을 극대화했습니다.",
                    "선택을 돕기 위해 확인된 특징들만 진솔하게 안내합니다."
                ],
                fact_ids[5:6],
            ),
            (
                "pre_purchase",
                "더 오랫동안 안심하고 쓰기 위해 구매 전 확인하세요",
                [
                    "제품의 상세한 구성품 구성과 지원 사양을 미리 확인해 주세요.",
                    "안정적인 사용 조건을 확인하시면 더욱 편리하게 쓰실 수 있습니다."
                ],
                fact_ids[6:7],
            ),
            (
                "specifications",
                "정직하게 작성된 상세한 제품 스펙",
                [
                    "기본 구성 패키지: 본품 기기 및 전원 연결용 부속 케이블, 설명서",
                    "핵심 사양: 편리한 분리 결합 설계 및 직관적 인터페이스 지원"
                ],
                fact_ids[7:8],
            ),
            (
                "caution",
                "안전한 제품 사용을 위해 반드시 지켜주실 주의사항",
                [
                    "기기에 무리한 힘을 가하거나 임의로 분해하지 말아주세요.",
                    "직사광선이 닿지 않고 습기가 없는 건조한 곳에 보관을 권장합니다."
                ],
                fact_ids[8:9],
            ),
            (
                "cta",
                f"지금 {product_name}와 함께 한결 더 편리한 하루를 시작해 보세요",
                [
                    "간편한 동작만으로 일상의 질을 높일 수 있는 기회를 놓치지 마세요.",
                    "당신의 라이프스타일에 맞춘 실용적인 만족을 제공해 드립니다."
                ],
                fact_ids[9:10],
            ),
        ]

        cards = []
        for idx, (card_type, title, bullets, source_facts) in enumerate(raw_cards):
            meta = CARD_METADATA[card_type]
            cards.append(
                {
                    "id": str(uuid.uuid4()),
                    "type": card_type,
                    "label": meta["label"],
                    "title": title,
                    "bullets": bullets,
                    "source_fact_ids": source_facts,
                    "visual_strategy": meta["visual_strategy"],
                    "is_enabled": True,
                    "sort_order": idx,
                }
            )

        return {"cards": cards}

    @staticmethod
    def _generate_llm_draft(
        project: ProductProject,
        normalized_data: Dict[str, Any],
        client: anthropic.Anthropic,
    ) -> Dict[str, Any]:
        product_facts = normalized_data.get("product_facts") or []
        needs_verification = normalized_data.get("needs_verification") or []

        facts_payload = [
            {"id": fact["id"], "text": fact["text"]}
            for fact in product_facts
        ]
        needs_verification_payload = [
            {"id": fact["id"], "text": fact["text"]}
            for fact in needs_verification
        ]

        system_prompt = (
            "당신은 상품 상세페이지 기획 초안을 만드는 전문 마케팅 플래너이자 카피라이터입니다.\n"
            "## 작성 원칙:\n"
            "1. 반드시 확인된 상품 사실(product_facts)과 판매자 입력만을 근거로 삼아 카피를 작성하십시오.\n"
            "2. 불확실하거나 검증이 필요한 정보(needs_verification)는 최종 카피에 단정적인 어조로 사용해서는 안 되며, 필요한 경우 '확인 필요'와 같은 톤으로 안전하게 서술하십시오.\n"
            "3. 소비자가 읽는 최종 상세페이지 문구이므로, AI나 마케터를 위한 내부 기획 지시문(예: '가장 먼저 보여줄 핵심 사용 가치를 한 문장으로 정리합니다', '상품 입력 정보를 바탕으로 안전한 표현을 사용합니다', '구매자가 불편을 느끼는 순간부터 보여주세요', '확인된 장점만 또렷하게 정리해요' 등)은 절대로 노출되지 않도록 하십시오.\n"
            "4. 과장된 최상급 표현('최고', '완벽', '무조건' 등)이나 어색한 마커('+', '—', '[AI 수정됨]' 등)는 절대 사용하지 마십시오.\n"
            "5. 제목은 '무엇을, 어디서, 왜 쓰는지'가 직관적이고 매력적으로 드러나도록 작성하십시오.\n"
            "6. 반드시 hero, target_customer, problem_situation, features, lifestyle_scene, comparison, pre_purchase, specifications, caution, cta 순서의 10개 카드를 생성하십시오."
        )
        user_content = (
            f"상품명: {project.name or '상품'}\n"
            f"판매자 입력 특징: {project.raw_input_text or ''}\n\n"
            f"확인된 상품 사실(product_facts):\n{json.dumps(facts_payload, ensure_ascii=False, indent=2)}\n\n"
            f"검증이 필요한 불확실한 사실(needs_verification):\n{json.dumps(needs_verification_payload, ensure_ascii=False, indent=2)}"
        )

        tool_definition = {
            "name": "generate_planning_draft",
            "description": "Generate exactly 10 planning draft cards based on verified product facts.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "cards": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": CARD_ORDER},
                                "title": {
                                    "type": "string",
                                    "description": "고객이 읽을 수 있는 매력적이고 자연스러운 섹션 제목 (기획 지시문 금지)"
                                },
                                "bullets": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "해당 섹션에 들어갈 고객 지향 판매 카피 목록 (AI 수정됨 등의 문구나 기획 지시문 금지)"
                                },
                                "source_fact_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "작성에 사용된 상품 사실 ID 리스트"
                                },
                                "visual_strategy": {
                                    "type": "string",
                                    "enum": ["image_overlay", "lifestyle_image", "text_only", "graphic_chart"],
                                },
                            },
                            "required": ["type", "title", "bullets", "source_fact_ids", "visual_strategy"],
                        },
                    }
                },
                "required": ["cards"],
            },
        }

        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=4000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
            tools=[tool_definition],
            tool_choice={"type": "tool", "name": "generate_planning_draft"},
            temperature=0.2,
        )

        tool_call = next((block for block in response.content if block.type == "tool_use"), None)
        if not tool_call or not tool_call.input:
            raise ValueError("LLM did not invoke generate_planning_draft")

        generated_cards = tool_call.input.get("cards") or []
        cards_by_type = {card.get("type"): card for card in generated_cards}

        cards = []
        for idx, card_type in enumerate(CARD_ORDER):
            source = cards_by_type.get(card_type) or {}
            meta = CARD_METADATA[card_type]
            cards.append(
                {
                    "id": str(uuid.uuid4()),
                    "type": card_type,
                    "label": meta["label"],
                    "title": source.get("title") or f"{meta['label']}를 보강해 주세요",
                    "bullets": source.get("bullets") or ["판매자가 검수하며 보강할 포인트입니다."],
                    "source_fact_ids": source.get("source_fact_ids") or [],
                    "visual_strategy": source.get("visual_strategy") or meta["visual_strategy"],
                    "is_enabled": True,
                    "sort_order": idx,
                }
            )

        return {"cards": cards}
