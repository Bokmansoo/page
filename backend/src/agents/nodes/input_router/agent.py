from src.agents.nodes.base import AgentNode
from src.agents.state import AgentRunState
from typing import Any

class InputRouterAgent(AgentNode):
    name = "input_router"

    def run(self, state: AgentRunState) -> AgentRunState:
        state.outputs[self.name] = {
            "input_type": "mixed",
            "missing_inputs": [],
        }
        return state

    def run_delta(self, *, run_id: str, input_snapshot: dict[str, Any]) -> dict[str, Any]:
        """LG-2 adapter: return a JSON state delta, never mutate graph state."""

        from src.services.langgraph_discovery_service import run_input_router

        return run_input_router(run_id=run_id, input_snapshot=input_snapshot)
