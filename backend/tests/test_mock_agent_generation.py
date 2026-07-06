from src.agents.mock_outputs import (
    build_mock_generated_assets,
    build_mock_page_assembly,
    build_mock_product_understanding,
)


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


def test_mock_page_assembly_references_assets_with_all_source_types():
    assets = build_mock_generated_assets(product_name="유아 자전거")["images"]
    assembly = build_mock_page_assembly(product_name="유아 자전거")
    asset_ids = {asset["id"] for asset in assets}

    assert {section["image_id"] for section in assembly["sections"]} <= asset_ids
    assert {asset["source_type"] for asset in assets} == {"mock-generated"}


def test_mock_graph_runs_to_qa_review():
    from src.agents.graph import AgentGraph
    from src.agents.state import AgentRunState, AgentStage, ProductInput
    
    graph = AgentGraph.mock()
    state = AgentRunState(project_id="p1", product_input=ProductInput(product_name="유아 자전거"))
    completed = graph.run_all(state)
    assert completed.current_stage == AgentStage.QA_REVIEW
    assert "product_understanding" in completed.outputs
    assert "sales_strategy" in completed.outputs
    assert "page_assembly" in completed.outputs
    assert completed.outputs["page_assembly"]["sections"]
