from src.agents.mock_outputs import build_mock_sales_strategy
from src.agents.nodes.base import AgentNode
from src.agents.schemas import SalesStrategyOutput
from src.agents.state import AgentRunState


class SalesStrategyAgent(AgentNode):
    name = "sales_strategy"

    def run(self, state: AgentRunState) -> AgentRunState:
        product_name = state.product_input.product_name or "상품"
        description = state.product_input.description or ""
        state.outputs[self.name] = build_mock_sales_strategy(product_name, description)
        return state

    def run_real_text(self, state: AgentRunState, generate_output) -> AgentRunState:
        state.outputs[self.name] = generate_output(
            "sales_strategy",
            self.name,
            {
                "product_input": state.product_input.model_dump(),
                "product_understanding": state.outputs.get("product_understanding"),
                "reference_analysis": state.outputs.get("reference_analysis"),
            },
            SalesStrategyOutput,
        )
        return state
