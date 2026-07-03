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
        pname = state.product_input.product_name or "유아 자전거"

        # 1. Product Understanding
        res_pu = self.text_provider.generate_json(
            ProviderRequest(
                provider="mock",
                model="mock-text",
                system_prompt="Analyze product.",
                user_prompt=pname,
                schema_name="product_understanding",
            )
        )
        pu_validated = ProductUnderstandingOutput.model_validate(res_pu["content"])
        state.outputs["product_understanding"] = pu_validated.model_dump()

        # 2. Sales Strategy
        res_ss = self.text_provider.generate_json(
            ProviderRequest(
                provider="mock",
                model="mock-text",
                system_prompt="Establish strategy.",
                user_prompt=pname,
                schema_name="sales_strategy",
            )
        )
        ss_validated = SalesStrategyOutput.model_validate(res_ss["content"])
        state.outputs["sales_strategy"] = ss_validated.model_dump()

        # 3. Page Plan
        res_pp = self.text_provider.generate_json(
            ProviderRequest(
                provider="mock",
                model="mock-text",
                system_prompt="Plan layout.",
                user_prompt=pname,
                schema_name="page_plan",
            )
        )
        pp_validated = DetailPagePlanOutput.model_validate(res_pp["content"])
        state.outputs["page_plan"] = pp_validated.model_dump()

        # 4. Copy Set
        res_cs = self.text_provider.generate_json(
            ProviderRequest(
                provider="mock",
                model="mock-text",
                system_prompt="Write copy.",
                user_prompt=pname,
                schema_name="copy_set",
            )
        )
        cs_validated = CopySetOutput.model_validate(res_cs["content"])
        state.outputs["copy_set"] = cs_validated.model_dump()

        # 5. Visual Plan
        res_vp = self.text_provider.generate_json(
            ProviderRequest(
                provider="mock",
                model="mock-text",
                system_prompt="Plan visuals.",
                user_prompt=pname,
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
                system_prompt="QA check.",
                user_prompt=pname,
                schema_name="qa_report",
            )
        )
        qa_validated = QAReportOutput.model_validate(res_qa["content"])
        state.outputs["qa_report"] = qa_validated.model_dump()

        # 7. Page Assembly (텍스트 프리뷰 구성용 mock)
        from src.agents.mock_outputs import build_mock_page_assembly
        state.outputs["page_assembly"] = build_mock_page_assembly(pname)

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

