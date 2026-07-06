from src.agents.mock_outputs import build_mock_product_understanding
from src.agents.nodes.base import AgentNode
from src.agents.schemas import ProductUnderstandingOutput
from src.agents.state import AgentRunState


class ProductUnderstandingAgent(AgentNode):
    name = "product_understanding"

    def run(self, state: AgentRunState) -> AgentRunState:
        product_name = state.product_input.product_name or "상품"
        description = state.product_input.description or ""
        state.outputs[self.name] = build_mock_product_understanding(product_name, description)
        return state

    def run_real_text(self, state: AgentRunState, generate_output) -> AgentRunState:
        state.outputs[self.name] = generate_output(
            "product_understanding",
            self.name,
            {"product_input": state.product_input.model_dump()},
            ProductUnderstandingOutput,
        )
        return state
