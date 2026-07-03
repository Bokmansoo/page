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
