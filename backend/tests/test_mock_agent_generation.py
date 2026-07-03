from backend.src.agents.mock_outputs import build_mock_product_understanding, build_mock_page_assembly


def test_mock_product_understanding_uses_input_name():
    result = build_mock_product_understanding(product_name="유아 자전거")
    assert result["product_type"] == "유아 자전거"
    assert "target_customer" in result
    assert result["verified_facts"]


def test_mock_page_assembly_has_copy_and_visual_slots():
    result = build_mock_page_assembly(product_name="유아 자전거")
    assert len(result["sections"]) >= 5
    assert all(section["title"] for section in result["sections"])
    assert all(section["visual_role"] for section in result["sections"])


def test_mock_graph_runs_to_review_editor():
    from backend.src.agents.graph import AgentGraph
    from backend.src.agents.state import AgentRunState, AgentStage, ProductInput
    
    graph = AgentGraph.mock()
    state = AgentRunState(project_id="p1", product_input=ProductInput(product_name="유아 자전거"))
    completed = graph.run_all(state)
    assert completed.current_stage == AgentStage.REVIEW_EDITOR
    assert "product_understanding" in completed.outputs
    assert "sales_strategy" in completed.outputs
    assert "page_assembly" in completed.outputs
    assert completed.outputs["page_assembly"]["sections"]

