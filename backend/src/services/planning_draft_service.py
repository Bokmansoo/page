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
from src.services.detail_page_template_service import DetailPageTemplateService

logger = logging.getLogger(__name__)


class PlanningDraftService:
    @staticmethod
    def generate_draft(
        project: ProductProject,
        confirmed_facts: List[ProductFact],
        db: Session,
    ) -> Dict[str, Any]:
        api_key = settings.ANTHROPIC_API_KEY
        is_mock = not api_key or settings.FACTORY_RAG_RUNTIME_MOCK

        # 1. Normalize facts using PageComposerService
        normalized_data = PageComposerService.normalize_facts(project, confirmed_facts)

        # 2. Select Template
        template_id = DetailPageTemplateService.select_template_id(project.category, project.intake_snapshot)
        template = DetailPageTemplateService.get_template(template_id)
        if not template:
            template = DetailPageTemplateService.get_template("general_sales")

        # 3. Generate initial draft
        if is_mock:
            logger.info(f"Generating deterministic planning draft fallback for template '{template['id']}'.")
            draft = PlanningDraftService._generate_mock_draft(project, normalized_data, template)
        else:
            try:
                client = anthropic.Anthropic(api_key=api_key)
                logger.info(f"Generating planning draft via Claude for template '{template['id']}'.")
                draft = PlanningDraftService._generate_llm_draft(project, normalized_data, template, client)
            except Exception as exc:
                logger.error(f"Failed to generate planning draft via Claude. Falling back: {exc}")
                draft = PlanningDraftService._generate_mock_draft(project, normalized_data, template)

        # 4. Apply CopyQualityGuard to clean and validate output
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

        # Record template info in response metadata
        draft["template_id"] = template["id"]
        draft["template_name"] = template["name"]
        return draft

    @staticmethod
    def _generate_mock_draft(project: ProductProject, normalized_data: Dict[str, Any], template: Dict[str, Any]) -> Dict[str, Any]:
        product_name = project.name or "상품"
        product_facts = normalized_data.get("product_facts") or []
        fact_ids = [f["id"] for f in product_facts]
        fact_texts = [f["text"] for f in product_facts]
        evidence_hint = fact_texts[0] if fact_texts else (project.raw_input_text or "")[:80]

        mock_templates_database = {
            "problem": (
                "매일 겪는 사소한 번거로움, 해결할 방법이 없을까 고민하셨나요?",
                ["작고 사소한 불편함들이 쌓이다 보면 일상이 조금씩 번거로워집니다.", "이제는 더 이상 미루지 말고 편리한 사용 경험으로 바꿔보세요."],
            ),
            "hero": (
                f"{product_name}, 필요한 순간 바로 쓰는 편리한 선택",
                [evidence_hint or "언제 어디서나 일상의 편리함을 한층 더 높여 줍니다.", "콘센트 연결 걱정 없이 시원함을 즉시 꺼내 쓸 수 있습니다."],
            ),
            "benefit_a": (
                "사용자를 깊이 배려한 이 제품만의 핵심 강점 A",
                ["누구나 쉽게 적응하고 직관적으로 사용할 수 있는 설계 구조", "엄격한 조립 공정을 거쳐 한층 안심하고 쓰실 수 있습니다."],
            ),
            "benefit_b": (
                "일상을 더 편리하게 만드는 추가 강점 B",
                ["가벼운 무게와 컴팩트한 디자인으로 어디든 부담 없이 이동 가능", "USB-C 포트 범용 충전 지원으로 뛰어난 호환성."],
            ),
            "hero_reemphasize": (
                f"다시 한번 느끼는 {product_name}의 차별화된 가치",
                ["복잡한 기능 대신 기본에 완벽히 충실하여 한결같이 편안합니다.", "오래도록 변치 않는 진정한 가치를 직접 경험해 보세요."],
            ),
            "benefits_summary": (
                "이 제품을 선택해야 하는 모든 이유를 정리했습니다",
                ["신뢰할 수 있는 배터리 탑재로 장시간 사용 시에도 발열 방지", "언제 어디서나 함께하는 일상의 든든한 동반자가 되어 줍니다."],
            ),
            "overall_summary": (
                f"한 문장으로 요약하는 {product_name}의 본질",
                [f"번거롭고 복잡한 일상을 가볍고 편안하게 바꿔주는 단 하나의 필수 아이템."],
            ),
            "product_info": (
                "정직하고 명확하게 작성된 상세한 제품 스펙",
                ["기본 구성 패키지: 본품 기기 및 전원 연결용 부속 케이블, 설명서", "핵심 사양: 편리한 분리 결합 설계 및 직관적 인터페이스 지원"],
            ),
            "target_customer": (
                f"이런 분들께 {product_name}를 적극 추천해 드려요",
                ["간편한 사용 방식과 실용성을 가장 중요하게 생각하시는 분", "기존 제품들의 번거로움에 지쳐 새로운 대안을 찾고 계셨던 분"],
            ),
            "caution": (
                "안전한 제품 사용을 위해 반드시 지켜주실 주의사항",
                ["기기에 무리한 힘을 가하거나 임의로 분해하지 말아주세요.", "직사광선이 닿지 않고 습기가 없는 건조한 곳에 보관을 권장합니다."],
            ),
            "cta": (
                f"지금 {product_name}와 함께 한결 더 편리한 하루를 시작해 보세요",
                ["간편한 동작만으로 일상의 질을 높일 수 있는 기회를 놓치지 마세요.", "당신의 라이프스타일에 맞춘 실용적인 만족을 제공해 드립니다."],
            ),
            "lifestyle_scene": (
                "당신의 소중한 공간 어디에나 자연스럽게 어울리는 일상",
                ["집, 사무실 등 사용 목적에 맞추어 어디서든 빛을 발합니다.", "감각적이고 미니멀한 디자인으로 공간의 분위기를 한층 돋보이게 합니다."],
            ),
            "comparison": (
                "비슷해 보이는 다른 제품들과의 차별점을 확인해 보세요",
                ["기능의 기본에 충실하면서도 사용의 편의성을 극대화했습니다.", "선택을 돕기 위해 확인된 특징들만 진솔하게 안내합니다."],
            ),
            "specifications": (
                "정직하게 작성된 상세한 제품 스펙",
                ["기본 구성 패키지: 본품 기기 및 전원 연결용 부속 케이블, 설명서", "핵심 사양: 편리한 분리 결합 설계 및 직관적 인터페이스 지원"],
            ),
            "pre_purchase": (
                "더 오랫동안 안심하고 쓰기 위해 구매 전 확인하세요",
                ["제품의 상세한 구성품 구성과 지원 사양을 미리 확인해 주세요.", "안정적인 사용 조건을 확인하시면 더욱 편리하게 쓰실 수 있습니다."],
            ),
        }

        cards = []
        for idx, sec in enumerate(template["sections"]):
            card_type = sec["type"]
            role = sec["role"]
            visual_strategy = sec["visual_strategy"]

            # Fallback mock values
            title, bullets = mock_templates_database.get(card_type, (f"{role} 타이틀", ["상세 카피 내용"]))
            
            # Map source facts dynamically
            source_facts = fact_ids[idx:idx+1] if idx < len(fact_ids) else []

            cards.append(
                {
                    "id": str(uuid.uuid4()),
                    "type": card_type,
                    "label": role,
                    "title": title,
                    "bullets": bullets,
                    "source_fact_ids": source_facts,
                    "visual_strategy": visual_strategy,
                    "is_enabled": True,
                    "sort_order": idx,
                }
            )

        return {"cards": cards}

    @staticmethod
    def _generate_llm_draft(
        project: ProductProject,
        normalized_data: Dict[str, Any],
        template: Dict[str, Any],
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

        template_card_types = [sec["type"] for sec in template["sections"]]
        template_card_desc = [f"- {sec['type']} ({sec['role']})" for sec in template["sections"]]

        system_prompt = (
            "당신은 상품 상세페이지 기획 초안을 만드는 전문 마케팅 플래너이자 카피라이터입니다.\n"
            "## 작성 원칙:\n"
            "1. 반드시 확인된 상품 사실(product_facts)과 판매자 입력만을 근거로 삼아 카피를 작성하십시오.\n"
            "2. 불확실하거나 검증이 필요한 정보(needs_verification)는 최종 카피에 단정적인 어조로 사용해서는 안 되며, 필요한 경우 '확인 필요'와 같은 톤으로 안전하게 서술하십시오.\n"
            "3. 소비자가 읽는 최종 상세페이지 문구이므로, AI나 마케터를 위한 내부 기획 지시문(예: '가장 먼저 보여줄 핵심 사용 가치를 한 문장으로 정리합니다' 등)은 절대로 노출되지 않도록 하십시오.\n"
            "4. 과장된 최상급 표현이나 어색한 마커는 절대 사용하지 마십시오.\n"
            "5. 제목은 '무엇을, 어디서, 왜 쓰는지'가 직관적이고 매력적으로 드러나도록 작성하십시오.\n"
            f"6. 반드시 다음 순서의 {len(template_card_types)}개 카드를 생성하십시오:\n" +
            "\n".join(template_card_desc)
        )
        user_content = (
            f"상품명: {project.name or '상품'}\n"
            f"판매자 입력 특징: {project.raw_input_text or ''}\n\n"
            f"확인된 상품 사실(product_facts):\n{json.dumps(facts_payload, ensure_ascii=False, indent=2)}\n\n"
            f"검증이 필요한 불확실한 사실(needs_verification):\n{json.dumps(needs_verification_payload, ensure_ascii=False, indent=2)}"
        )

        tool_definition = {
            "name": "generate_planning_draft",
            "description": f"Generate exactly {len(template_card_types)} planning draft cards based on the selected template structure.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "cards": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": template_card_types},
                                "title": {
                                    "type": "string",
                                    "description": "고객이 읽을 수 있는 매력적이고 자연스러운 섹션 제목"
                                },
                                "bullets": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "해당 섹션에 들어갈 고객 지향 판매 카피 목록"
                                },
                                "source_fact_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "작성에 사용된 상품 사실 ID 리스트"
                                },
                                "visual_strategy": {
                                    "type": "string",
                                    "enum": ["image_overlay", "lifestyle_image", "text_only", "graphic_chart", "html_graphic"],
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
        for idx, sec in enumerate(template["sections"]):
            card_type = sec["type"]
            role = sec["role"]
            visual_strategy = sec["visual_strategy"]

            source = cards_by_type.get(card_type) or {}
            cards.append(
                {
                    "id": str(uuid.uuid4()),
                    "type": card_type,
                    "label": role,
                    "title": source.get("title") or f"{role}를 보강해 주세요",
                    "bullets": source.get("bullets") or ["판매자가 검수하며 보강할 포인트입니다."],
                    "source_fact_ids": source.get("source_fact_ids") or [],
                    "visual_strategy": source.get("visual_strategy") or visual_strategy,
                    "is_enabled": True,
                    "sort_order": idx,
                }
            )

        return {"cards": cards}
