from src.agents.nodes.base import AgentNode
from src.agents.state import AgentRunState

class InputRouterAgent(AgentNode):
    name = "input_router"

    def run(self, state: AgentRunState) -> AgentRunState:
        state.outputs[self.name] = {
            "input_type": "mixed",
            "missing_inputs": [],
        }
        return state
