from src.agents.mock_outputs import build_mock_page_plan
from src.agents.nodes.base import AgentNode
from src.agents.schemas import DetailPagePlanOutput
from src.agents.state import AgentRunState


class PagePlanningAgent(AgentNode):
    name = "page_planning"

    def run(self, state: AgentRunState) -> AgentRunState:
        product_name = state.product_input.product_name or "상품"
        state.outputs[self.name] = build_mock_page_plan(product_name)
        return state

    def run_real_text(self, state: AgentRunState, generate_output) -> AgentRunState:
        state.outputs[self.name] = generate_output(
            "page_plan",
            self.name,
            {
                "product_input": state.product_input.model_dump(),
                "product_understanding": state.outputs.get("product_understanding"),
                "sales_strategy": state.outputs.get("sales_strategy"),
            },
            DetailPagePlanOutput,
        )
        return state

    def run_delta(self, *, run_id: str, project_id: str, mode: str) -> dict:
        from src.services.langgraph_commerce_planning_service import run_page_planning

        return run_page_planning(run_id=run_id, project_id=project_id, mode=mode)
