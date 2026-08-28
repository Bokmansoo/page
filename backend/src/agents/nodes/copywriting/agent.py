from src.agents.mock_outputs import build_mock_copy_set
from src.agents.nodes.base import AgentNode
from src.agents.schemas import CopySetOutput
from src.agents.state import AgentRunState


class CopywritingAgent(AgentNode):
    name = "copywriting"

    def run(self, state: AgentRunState) -> AgentRunState:
        product_name = state.product_input.product_name or "상품"
        description = state.product_input.description or ""
        state.outputs[self.name] = build_mock_copy_set(
            product_name,
            description,
            category=state.product_input.category,
            facts=(state.input_snapshot or {}).get("approved_facts") or [],
            components=state.product_input.components,
            cautions=state.product_input.cautions,
        )
        return state

    def run_real_text(self, state: AgentRunState, generate_output) -> AgentRunState:
        state.outputs[self.name] = generate_output(
            "copy_set",
            self.name,
            {
                "product_input": state.product_input.model_dump(),
                "product_understanding": state.outputs.get("product_understanding"),
                "sales_strategy": state.outputs.get("sales_strategy"),
                "page_plan": state.outputs.get("page_planning"),
            },
            CopySetOutput,
        )
        return state

    def run_delta(self, *, run_id: str, project_id: str, mode: str) -> dict:
        from src.services.langgraph_commerce_planning_service import run_copywriting

        return run_copywriting(run_id=run_id, project_id=project_id, mode=mode)
