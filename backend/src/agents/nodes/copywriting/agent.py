from src.agents.mock_outputs import build_mock_copy_set
from src.agents.nodes.base import AgentNode
from src.agents.schemas import CopySetOutput
from src.agents.state import AgentRunState


class CopywritingAgent(AgentNode):
    name = "copywriting"

    def run(self, state: AgentRunState) -> AgentRunState:
        product_name = state.product_input.product_name or "상품"
        description = state.product_input.description or ""
        state.outputs[self.name] = build_mock_copy_set(product_name, description)
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
