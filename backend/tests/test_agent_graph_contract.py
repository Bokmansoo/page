from backend.src.agents.graph import AgentGraph
from backend.src.agents.state import AgentRunState, AgentStage, ProductInput


def test_mock_graph_advances_from_intake_to_product_understanding():
    graph = AgentGraph.mock()
    state = AgentRunState(project_id="p1", product_input=ProductInput(product_name="유아 자전거"))
    next_state = graph.run_next(state)
    assert next_state.current_stage == AgentStage.PRODUCT_UNDERSTANDING
    assert "product_understanding" in next_state.outputs
