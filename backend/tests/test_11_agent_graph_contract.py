from src.agents.state import AgentStage


def test_11_agent_stage_order_is_final_product_pipeline():
    assert [stage.value for stage in AgentStage] == [
        "input_router",
        "source_collection",
        "product_understanding",
        "reference_analysis",
        "sales_strategy",
        "page_planning",
        "copywriting",
        "visual_planning",
        "image_generation",
        "page_assembly",
        "qa_review",
    ]


def test_graph_runs_all_11_nodes_in_mock_mode():
    from src.agents.graph import AgentGraph
    from src.agents.state import AgentRunState

    state = AgentRunState(
        project_id="project-1",
        input_snapshot={"product_name": "삼성 삼탠바이미 32인치 스마트모니터"},
    )
    result = AgentGraph.mock().run(state)

    # We also verify it runs the 11 nodes.
    # Note: reference_analysis could be skipped but its trace output is still included in outputs.
    # We filter only the 11 main stages from outputs keys to prevent compatibility keys like 'legacy' from failing the order assert.
    stages = [
        "input_router",
        "source_collection",
        "product_understanding",
        "reference_analysis",
        "sales_strategy",
        "page_planning",
        "copywriting",
        "visual_planning",
        "image_generation",
        "page_assembly",
        "qa_review",
    ]
    actual_stages = [k for k in result.outputs.keys() if k in stages]
    assert actual_stages == stages


