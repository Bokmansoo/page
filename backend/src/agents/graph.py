from backend.src.agents.state import AgentRunState, AgentStage


class AgentGraph:
    def __init__(self, is_mock: bool = True):
        self.is_mock = is_mock

    @classmethod
    def mock(cls) -> "AgentGraph":
        return cls(is_mock=True)

    def run_next(self, state: AgentRunState) -> AgentRunState:
        # Handle INTAKE -> PRODUCT_UNDERSTANDING stage transition
        if state.current_stage == AgentStage.INTAKE:
            state.current_stage = AgentStage.PRODUCT_UNDERSTANDING
            state.outputs["product_understanding"] = {
                "mocked": True,
                "product_name": state.product_input.product_name,
                "facts": ["검증된 사실 1"],
            }
        return state

    def run_all(self, state: AgentRunState) -> AgentRunState:
        from backend.src.agents.mock_outputs import (
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
