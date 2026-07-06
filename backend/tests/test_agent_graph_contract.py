from src.agents.graph import AgentGraph
from src.agents.state import AgentRunMode, AgentRunState, AgentStage, ProductInput
from src.services.provider_adapters import MockTextProvider


def test_mock_graph_advances_from_input_router_to_source_collection():
    graph = AgentGraph.mock()
    state = AgentRunState(project_id="p1", product_input=ProductInput(product_name="유아 자전거"))
    next_state = graph.run_next(state)
    assert next_state.current_stage == AgentStage.SOURCE_COLLECTION
    assert "source_collection" in next_state.outputs


def test_real_text_graph_reports_actual_agent_progress():
    class PassingAgent:
        name = "input_router"

        def run_real_text(self, state, generate_output):
            state.outputs[self.name] = {"routed": True}
            return state

    graph = AgentGraph.real_text(text_provider=MockTextProvider())
    graph.agents = [PassingAgent()]
    state = AgentRunState(
        project_id="p1",
        mode=AgentRunMode.REAL,
        product_input=ProductInput(product_name="유아 자전거"),
    )
    events = []

    graph.run_text_generation(
        state,
        progress_callback=lambda stage, status, current_state, error: events.append(
            (stage, status, current_state.current_stage.value, error)
        ),
    )

    assert events == [
        ("input_router", "running", "input_router", None),
        ("input_router", "completed", "input_router", None),
    ]
