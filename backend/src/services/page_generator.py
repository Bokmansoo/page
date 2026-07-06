import time
import json
import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import anthropic
from src.config import settings

logger = logging.getLogger(__name__)

PROBLEM_SOLUTION_SECTION_TYPES = [
    "problem_statement",
    "main_claim",
    "secondary_benefit",
    "main_claim_support",
    "benefit_list",
    "summary_claim",
    "product_information",
]

# =====================================================================
# Pydantic Schemas for AI Generation
# =====================================================================

class GeneratedSectionSchema(BaseModel):
    section_type: str = Field(description="섹션 유형 (header, features, specifications, faq, etc.)")
    title: str = Field(description="이 섹션의 매력적인 소제목 또는 타이틀")
    body_copy: str = Field(description="이 섹션에 들어갈 셀링 포인트가 담긴 한국어 판매 카피 문구")
    associated_fact_ids: List[str] = Field(description="이 섹션의 판매 카피를 작성할 때 반영한 확정된 사실 카드 ID들의 리스트")

class GeneratedPageSchema(BaseModel):
    theme_color: str = Field(description="상세페이지 브랜드 톤에 어울리는 추천 대표 테마 색상 (Hex 코드, 예: '#3B82F6')")
    font_family: str = Field(description="추천 폰트 스타일 (sans-serif, serif, monospace, cursive 중 하나)")
    sections: List[GeneratedSectionSchema] = Field(description="상세페이지를 구성하는 순서대로 정렬된 섹션들")


# =====================================================================
# Core Page Generation Service
# =====================================================================

class PageGenerationService:
    def __init__(self, api_key: Optional[str] = None, model_name: str = "claude-3-5-sonnet-20241022"):
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        self.model_name = model_name
        self.client = anthropic.Anthropic(api_key=self.api_key) if self.api_key else None
        if not self.client:
            logger.warning("Anthropic API Key가 누락되었습니다. 상세페이지 생성 시 Mock 데이터를 반환합니다.")

    def generate_page(
        self,
        category: str,
        confirmed_facts: List[Dict[str, Any]],
        style_preset: str = "modern",
        primary_color: Optional[str] = None,
        narrative_template: str = "category_default",
        sales_strategy: Optional[Dict[str, Any]] = None
    ) -> GeneratedPageSchema:
        """
        Call Claude 3.5 Sonnet to design layout and copy of product page based on confirmed facts.
        """
        # API Key가 없는 경우 또는 Mock 동작 조건 시 Mock 응답 제공 (안전장치)
        if not self.client or settings.FACTORY_RAG_RUNTIME_MOCK:
            logger.info("Mocking Claude 3.5 Sonnet page generation response.")
            return self._get_mock_page(category, confirmed_facts, primary_color, narrative_template, sales_strategy)


        narrative_instruction = self._get_narrative_template_instruction(narrative_template, category)

        system_prompt = (
            "당신은 확정된 상품 사실(Fact)들만을 정교하게 엮어서, 마케팅 효율이 높은 온라인 상세페이지 설명 레이아웃과 판매 카피를 작성하는 탑클래스 카피라이터이자 디자이너입니다.\n"
            f"주어진 상품 카테고리({category})와 스타일 프리셋({style_preset})에 적합하도록 상세페이지 구조(섹션들)와 각 섹션의 제목(title), 카피(body_copy)를 작성하십시오.\n"
            f"내러티브 템플릿 지시: {narrative_instruction}\n"
            "규칙:\n"
            "1. 본문 카피는 절대로 지어내거나 입증되지 않은 정보를 포함해서는 안 됩니다. 오직 제공된 확정 사실들(confirmed facts)만을 근거로 작성하십시오.\n"
            "2. 각 섹션마다 카피 작성에 사용된 사실들의 ID(UUID)를 associated_fact_ids 필드에 매핑하여 출력하십시오. 사실을 임의로 왜곡하여 매핑해서는 안 됩니다.\n"
            "3. 한국어로만 작성하고, 문체는 친근하면서도 신뢰감을 주는 서술형 및 설득형 문장을 구사하십시오."
        )

        # 팩트 데이터를 텍스트로 가공
        facts_payload = []
        for fact in confirmed_facts:
            facts_payload.append({
                "id": fact["id"],
                "text": fact["fact_text"],
                "source": fact.get("source_text", "")
            })

        user_content = self._build_user_content(
            category=category,
            facts_payload=facts_payload,
            sales_strategy=sales_strategy,
        )

        # Anthropic 도구 강제 지정을 통해 구조화 응답 획득
        tool_definition = {
            "name": "generate_product_page",
            "description": "Generate product detail page outline and sales copywriting based on facts.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "theme_color": {
                        "type": "string",
                        "description": "추천 대표 테마 색상 (예: '#FF5733')"
                    },
                    "font_family": {
                        "type": "string",
                        "enum": ["sans-serif", "serif", "monospace", "cursive"],
                        "description": "추천 폰트 스타일"
                    },
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "section_type": {
                                    "type": "string",
                                    "description": "섹션 종류 (header, features, specifications, faq 등. 만약 내러티브 템플릿이 problem_solution인 경우 반드시 problem_statement, main_claim, secondary_benefit, main_claim_support, benefit_list, summary_claim, product_information 순서로 지정하십시오.)"
                                },
                                "title": {
                                    "type": "string",
                                    "description": "섹션 타이틀"
                                },
                                "body_copy": {
                                    "type": "string",
                                    "description": "섹션에 들어갈 매끄럽고 매력적인 한국어 판매 카피"
                                },
                                "associated_fact_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "작성에 사용된 상품 사실 ID 리스트"
                                }
                            },
                            "required": ["section_type", "title", "body_copy", "associated_fact_ids"]
                        }
                    }
                },
                "required": ["theme_color", "font_family", "sections"]
            }
        }

        try:
            response = self.client.messages.create(
                model=self.model_name,
                max_tokens=4000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
                tools=[tool_definition],
                tool_choice={"type": "tool", "name": "generate_product_page"},
                temperature=0.2
            )

            tool_call = next(
                (content for content in response.content if content.type == "tool_use"), None
            )
            if not tool_call:
                raise ValueError("Claude API가 상세페이지 빌드용 도구 응답을 반환하지 않았습니다.")

            raw_result = tool_call.input
            
            # 주입된 primary_color가 있는 경우 우선 적용
            if primary_color:
                raw_result["theme_color"] = primary_color

            generated_page = GeneratedPageSchema.model_validate(raw_result)
            self._validate_generated_page(
                generated_page,
                category=category,
                narrative_template=narrative_template,
                confirmed_facts=confirmed_facts,
            )
            return generated_page

        except Exception as e:
            logger.error(f"Claude 상세페이지 생성 중 오류 발생: {e}. Mock 폴백 적용.", exc_info=True)
            return self._get_mock_page(
                category,
                confirmed_facts,
                primary_color,
                narrative_template,
                sales_strategy,
            )

    @staticmethod
    def _build_user_content(
        category: str,
        facts_payload: List[Dict[str, Any]],
        sales_strategy: Optional[Dict[str, Any]] = None,
    ) -> str:
        strategy_payload = sales_strategy or {}
        return (
            f"카테고리: {category}\n"
            "확정 판매 전략:\n"
            f"{json.dumps(strategy_payload, ensure_ascii=False, indent=2)}\n"
            "확정 사실 카드 목록:\n"
            f"{json.dumps(facts_payload, ensure_ascii=False, indent=2)}"
        )

    @staticmethod
    def _short_fact_summary(facts: list[dict], max_chars: int = 120) -> str:
        text = " ".join([fact.get("fact_text", "") for fact in facts])
        blocked_keywords = ["KC 인증", "상품번호", "제조", "수입", "인증정보"]
        sentences = [sentence.strip() for sentence in text.split(".") if sentence.strip()]
        sales_sentences = [
            sentence for sentence in sentences if not any(keyword in sentence for keyword in blocked_keywords)
        ]
        summary = ". ".join(sales_sentences[:2] or sentences[:1]).strip()
        if summary and not summary.endswith("."):
            summary += "."
        if len(summary) > max_chars:
            summary = summary[: max_chars - 1].rstrip() + "…"
        return summary


    def _get_mock_page(
        self,
        category: str,
        confirmed_facts: List[Dict[str, Any]],
        primary_color: Optional[str] = None,
        narrative_template: str = "category_default",
        sales_strategy: Optional[Dict[str, Any]] = None
    ) -> GeneratedPageSchema:
        """
        Generate mock detail page content if API is unavailable or offline.
        """
        if narrative_template == "problem_solution":
            return self._get_problem_solution_mock_page(category, confirmed_facts, primary_color, sales_strategy)

        color = primary_color or "#3B82F6"
        fact_ids = [f["id"] for f in confirmed_facts]


        # 기본 팩트 텍스트 조합
        fact_summary = self._short_fact_summary(confirmed_facts) if confirmed_facts else "기본 검증된 상품 정보 기준 작성."

        # 카테고리별 테마 스타일 설정
        cat = category.lower()
        if cat == "fashion":
            sections = [
                GeneratedSectionSchema(
                    section_type="header",
                    title="스타일리시한 아웃핏의 기준",
                    body_copy="매일 입어도 질리지 않는 편안함과 모던한 핏감을 동시에 선사합니다.",
                    associated_fact_ids=fact_ids[:1] if fact_ids else []
                ),
                GeneratedSectionSchema(
                    section_type="features",
                    title="엄선된 소재와 품질",
                    body_copy=f"본 상품은 꼼꼼한 마감과 고품질 공정으로 탄생했습니다. {fact_summary}",
                    associated_fact_ids=fact_ids
                )
            ]
        elif cat == "beauty":
            sections = [
                GeneratedSectionSchema(
                    section_type="header",
                    title="피부 스스로 숨쉬는 아름다움",
                    body_copy="지친 피부에 즉각적인 수분을 전하고 진정한 생기를 부여해 드립니다.",
                    associated_fact_ids=fact_ids[:1] if fact_ids else []
                ),
                GeneratedSectionSchema(
                    section_type="features",
                    title="성분에서 시작되는 놀라운 변화",
                    body_copy=f"안전하게 엄선된 주요 성분들이 깊숙이 흡수되어 장벽 개선을 돕습니다. {fact_summary}",
                    associated_fact_ids=fact_ids
                )
            ]
        elif cat == "food":
            sections = [
                GeneratedSectionSchema(
                    section_type="header",
                    title="자연에서 온 신선함 그대로",
                    body_copy="우리 가족이 매일 안심하고 먹을 수 있는 건강하고 정직한 먹거리입니다.",
                    associated_fact_ids=fact_ids[:1] if fact_ids else []
                ),
                GeneratedSectionSchema(
                    section_type="features",
                    title="영양과 맛을 담은 고집",
                    body_copy=f"원재료의 깊고 풍부한 풍미를 그대로 살려 제조했습니다. {fact_summary}",
                    associated_fact_ids=fact_ids
                )
            ]
        else:  # living
            sections = [
                GeneratedSectionSchema(
                    section_type="header",
                    title="일상 공간에 가치를 더하다",
                    body_copy="실용적인 디자인과 견고한 만듦새로 당신의 라이프스타일을 완성합니다.",
                    associated_fact_ids=fact_ids[:1] if fact_ids else []
                ),
                GeneratedSectionSchema(
                    section_type="features",
                    title="견고하고 조화로운 설계",
                    body_copy=f"우수한 내구성과 세련된 미감으로 오래 두고 사용해도 아름답습니다. {fact_summary}",
                    associated_fact_ids=fact_ids
                )
            ]

        return GeneratedPageSchema(
            theme_color=color,
            font_family="sans-serif",
            sections=sections
        )

    def _get_problem_solution_mock_page(
        self,
        category: str,
        confirmed_facts: List[Dict[str, Any]],
        primary_color: Optional[str] = None,
        sales_strategy: Optional[Dict[str, Any]] = None,
    ) -> GeneratedPageSchema:
        from src.services.style_strategy_service import get_category_frame

        color = primary_color or "#3B82F6"
        fact_ids = [f["id"] for f in confirmed_facts]
        fact_summary = self._short_fact_summary(confirmed_facts) if confirmed_facts else "확인된 상품 정보를 기준으로 구성했습니다."
        category_key = category.lower()

        # Get the category frame sections
        frame = get_category_frame(category)
        
        buyer_problem = ""
        main_selling_point = ""
        if sales_strategy:
            buyer_problem = sales_strategy.get("buyer_problem", "")
            main_selling_point = sales_strategy.get("main_selling_point", "")

        # We need to construct sections matching the frame structure!
        sections = []
        for idx, sec_frame in enumerate(frame.sections):
            # Default text based on section type
            title = sec_frame.label
            body_copy = f"{sec_frame.description} {fact_summary}"
            
            # If it's the first section, customize its title
            if idx == 0:
                problem_title_by_category = {
                    "fashion": "매일 입을 옷, 예쁘기만 하면 충분할까요?",
                    "beauty": "피부 고민, 아무 제품이나 고르기 어려우니까",
                    "food": "매일 먹는 것일수록 원재료 and 편의성이 중요합니다",
                    "living": "작은 불편이 쌓이면 일상이 번거로워집니다",
                }
                title = problem_title_by_category.get(category_key, "이 상품이 필요한 이유부터 짚어볼게요")
                body_copy = buyer_problem or "고객이 실제로 느끼는 불편과 구매 전 고민을 먼저 짚어줍니다."

            elif idx == 1:
                title = main_selling_point or "핵심 문제를 줄여주는 선택"
                body_copy = f"이 상품은 확인된 상품 정보를 바탕으로 핵심 구매 이유를 제안합니다. {fact_summary}"
            elif idx == 2:
                title = "함께 챙길 수 있는 추가 장점"
                body_copy = "메인 소구점 외에도 사용자가 체감할 수 있는 보조 장점을 정리합니다."
            elif idx == 3:
                title = "왜 이 상품이어야 할까요?"
                body_copy = "핵심 메시지를 다시 한 번 근거 중심으로 보강합니다."
            elif idx == 4:
                title = "구매 전 확인할 장점들"
                body_copy = "나머지 장점을 보기 쉽게 정리해 구매 판단을 돕습니다."
            elif idx == 5:
                title = "한 문장으로 정리하면"
                body_copy = "필요한 이유와 기대할 수 있는 장점을 한 문장으로 요약합니다."
            elif idx == 6:
                title = "상품 정보"
                body_copy = "최종 구매 판단에 필요한 정보입니다. " + " ".join([f["fact_text"] for f in confirmed_facts])

            sections.append(GeneratedSectionSchema(
                section_type=sec_frame.key,
                title=title,
                body_copy=body_copy,
                associated_fact_ids=fact_ids
            ))

        page = GeneratedPageSchema(
            theme_color=color,
            font_family="sans-serif",
            sections=sections
        )

        category_copy = {
            "fashion": (
                "코디와 착용 부담을 덜어주는 선택",
                "착용감과 활용도에 대한 고민을 확인된 상품 정보로 풀어봅니다.",
                "스타일에 더하는 실용적인 장점",
            ),
            "beauty": (
                "성분과 사용 정보를 보고 고르는 선택",
                "사용 전 확인하고 싶은 정보를 확인된 상품 사실로 정리합니다.",
                "루틴에 더하는 사용 편의",
            ),
            "food": (
                "원재료와 구성 정보를 보고 고르는 선택",
                "식품을 고를 때 필요한 정보를 확인된 상품 사실로 정리합니다.",
                "식탁에 더하는 선택의 이유",
            ),
            "living": (
                "일상의 불편을 덜어주는 실용적인 선택",
                "사용 환경에서 확인할 정보를 확인된 상품 사실로 정리합니다.",
                "공간과 사용 경험에 더하는 장점",
            ),
        }.get(category_key, (
            "확인된 정보로 고르는 선택",
            "구매 전에 확인할 정보를 상품 사실로 정리합니다.",
            "함께 확인할 추가 장점",
        ))
        page.sections[1].title = category_copy[0]
        page.sections[1].body_copy = f"{category_copy[1]} {fact_summary}"
        page.sections[2].title = category_copy[2]
        return page

    def _get_narrative_template_instruction(self, narrative_template: str, category: str) -> str:
        if narrative_template == "problem_solution":
            from src.services.style_strategy_service import get_category_frame
            frame = get_category_frame(category)
            keys_str = ", ".join([f"{sec.key}({sec.label})" for sec in frame.sections])
            return (
                f"상세페이지는 반드시 다음 7개 섹션 순서를 따르십시오: {keys_str}. "
                "각 섹션은 확인된 사실만 근거로 작성하고 associated_fact_ids를 정확히 연결하십시오."
            )
        return "카테고리와 스타일에 맞는 일반 상세페이지 구조를 생성하십시오."

    def _validate_generated_page(
        self,
        page: GeneratedPageSchema,
        category: str,
        narrative_template: str,
        confirmed_facts: List[Dict[str, Any]],
    ) -> None:
        from src.services.style_strategy_service import get_category_frame

        confirmed_fact_ids = {str(fact["id"]) for fact in confirmed_facts}
        for section in page.sections:
            invalid_fact_ids = set(section.associated_fact_ids) - confirmed_fact_ids
            if invalid_fact_ids:
                raise ValueError("Generated page contains unconfirmed fact IDs")

        if narrative_template == "problem_solution":
            expected_keys = [sec.key for sec in get_category_frame(category).sections]
            section_types = [section.section_type for section in page.sections]
            if section_types != expected_keys:
                raise ValueError("Problem-solution sections do not match the required order")
