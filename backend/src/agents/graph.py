from src.agents.state import AgentRunState, AgentStage
from src.agents.schemas import (
    ProductUnderstandingOutput,
    SalesStrategyOutput,
    DetailPagePlanOutput,
    CopySetOutput,
    VisualPlanOutput,
    QAReportOutput,
)
from src.services.provider_adapters import ProviderRequest


class AgentGraph:
    def __init__(self, is_mock: bool = True):
        self.is_mock = is_mock
        self.text_provider = None

    @classmethod
    def mock(cls) -> "AgentGraph":
        return cls(is_mock=True)

    @classmethod
    def real_text(cls, text_provider) -> "AgentGraph":
        instance = cls(is_mock=False)
        instance.text_provider = text_provider
        return instance

    def run_next(self, state: AgentRunState) -> AgentRunState:
        if state.current_stage == AgentStage.INTAKE:
            state.current_stage = AgentStage.PRODUCT_UNDERSTANDING
            state.outputs["product_understanding"] = {
                "mocked": True,
                "product_name": state.product_input.product_name,
                "facts": ["검증된 사실 1"],
            }
        return state

    def run_text_generation(self, state: AgentRunState) -> AgentRunState:
        import json
        from src.services.prompt_registry import PromptRegistry

        pname = state.product_input.product_name or "유아 자전거"
        description = state.product_input.description or "설명 없음"
        url = state.product_input.product_url or "URL 없음"

        registry = PromptRegistry()
        system_base = registry.load("system_base")

        # 1. Product Understanding
        pu_sys = system_base + "\n" + registry.load("product_understanding")
        pu_user = f"상품명: {pname}\n상품설명: {description}\n상품URL: {url}"

        res_pu = self.text_provider.generate_json(
            ProviderRequest(
                provider="mock",
                model="mock-text",
                system_prompt=pu_sys,
                user_prompt=pu_user,
                schema_name="product_understanding",
            )
        )
        pu_validated = ProductUnderstandingOutput.model_validate(res_pu["content"])
        state.outputs["product_understanding"] = pu_validated.model_dump()

        # 2. Sales Strategy
        ss_sys = system_base + "\n" + registry.load("sales_strategy")
        ss_user = f"상품 정보: {json.dumps(state.outputs['product_understanding'], ensure_ascii=False)}"

        res_ss = self.text_provider.generate_json(
            ProviderRequest(
                provider="mock",
                model="mock-text",
                system_prompt=ss_sys,
                user_prompt=ss_user,
                schema_name="sales_strategy",
            )
        )
        ss_validated = SalesStrategyOutput.model_validate(res_ss["content"])
        state.outputs["sales_strategy"] = ss_validated.model_dump()

        # 3. Page Plan
        pp_sys = system_base + "\n" + registry.load("page_planning")
        pp_user = f"마케팅 전략: {json.dumps(state.outputs['sales_strategy'], ensure_ascii=False)}"

        res_pp = self.text_provider.generate_json(
            ProviderRequest(
                provider="mock",
                model="mock-text",
                system_prompt=pp_sys,
                user_prompt=pp_user,
                schema_name="page_plan",
            )
        )
        pp_validated = DetailPagePlanOutput.model_validate(res_pp["content"])
        state.outputs["page_plan"] = pp_validated.model_dump()

        # 4. Copy Set
        cs_sys = system_base + "\n" + registry.load("copywriting")
        cs_user = f"레이아웃 구조: {json.dumps(state.outputs['page_plan'], ensure_ascii=False)}"

        res_cs = self.text_provider.generate_json(
            ProviderRequest(
                provider="mock",
                model="mock-text",
                system_prompt=cs_sys,
                user_prompt=cs_user,
                schema_name="copy_set",
            )
        )
        cs_validated = CopySetOutput.model_validate(res_cs["content"])
        state.outputs["copy_set"] = cs_validated.model_dump()

        # 5. Visual Plan
        vp_sys = system_base + "\n" + registry.load("visual_planning")
        vp_user = f"마케팅 카피: {json.dumps(state.outputs['copy_set'], ensure_ascii=False)}"

        res_vp = self.text_provider.generate_json(
            ProviderRequest(
                provider="mock",
                model="mock-text",
                system_prompt=vp_sys,
                user_prompt=vp_user,
                schema_name="visual_plan",
            )
        )
        vp_validated = VisualPlanOutput.model_validate(res_vp["content"])
        state.outputs["visual_plan"] = vp_validated.model_dump()

        # 6. QA Report
        res_qa = self.text_provider.generate_json(
            ProviderRequest(
                provider="mock",
                model="mock-text",
                system_prompt=system_base + "\n" + registry.load("qa_review"),
                user_prompt=f"작성본 데이터: {json.dumps(state.outputs, ensure_ascii=False)}",
                schema_name="qa_report",
            )
        )
        qa_validated = QAReportOutput.model_validate(res_qa["content"])
        state.outputs["qa_report"] = qa_validated.model_dump()

        # 7. Page Assembly (LLM 결과 기반 동적 조립)
        copy_set = state.outputs.get("copy_set", {})
        page_plan = state.outputs.get("page_plan", {})
        sections_plan = page_plan.get("sections", [])

        assembled_sections = []
        role_map = {
            0: ("hero", "mock-hero-visual", copy_set.get("hero_title", ""), copy_set.get("hero_subtitle", "")),
            1: ("comparison", "mock-comparison-visual", copy_set.get("painpoint_title", ""), "흔들리는 저가형 제품과 비교해 보세요."),
            2: ("detail_1", "mock-detail-1-visual", copy_set.get("feature_1_title", ""), "체형 변화에 맞춰 편리하게 안장 높이를 조절합니다."),
            3: ("detail_2", "mock-detail-2-visual", copy_set.get("feature_2_title", ""), "KC 유해물질 검사를 완료하여 안심하고 태울 수 있습니다."),
            4: ("guarantee", "mock-guarantee-visual", "안심 구매 보장 & 정품 마크", copy_set.get("cta_text", "지금 구매하기")),
        }

        for idx, sec in enumerate(sections_plan):
            sec_id = sec.get("id") or f"sec-{idx+1}"
            sec_name = sec.get("name") or "세부 정보"
            role_data = role_map.get(idx, ("detail_1", "mock-detail-1-visual", sec_name, "상세 정보 설명"))
            
            assembled_sections.append({
                "id": sec_id,
                "title": role_data[2],
                "body": role_data[3],
                "visual_role": role_data[0],
                "image_id": role_data[1],
            })

        state.outputs["page_assembly"] = {
            "sections": assembled_sections
        }

        state.current_stage = AgentStage.REVIEW_EDITOR
        return state

    def run_all(self, state: AgentRunState) -> AgentRunState:
        from src.agents.mock_outputs import (
            build_mock_product_understanding,
            build_mock_sales_strategy,
            build_mock_page_plan,
            build_mock_copy_set,
            build_mock_visual_plan,
            build_mock_generated_assets,
            build_mock_page_assembly,
            build_mock_qa_report,
        )

        pname = state.product_input.product_name or "무명 상품"

        state.outputs["product_understanding"] = build_mock_product_understanding(pname)
        state.outputs["sales_strategy"] = build_mock_sales_strategy(pname)
        state.outputs["page_plan"] = build_mock_page_plan(pname)
        state.outputs["copy_set"] = build_mock_copy_set(pname)
        state.outputs["visual_plan"] = build_mock_visual_plan(pname)
        state.outputs["generated_assets"] = build_mock_generated_assets(pname)
        state.outputs["page_assembly"] = build_mock_page_assembly(pname)
        state.outputs["qa_report"] = build_mock_qa_report(pname)

        state.current_stage = AgentStage.REVIEW_EDITOR
        return state

