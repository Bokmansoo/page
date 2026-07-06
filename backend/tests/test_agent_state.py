from src.agents.state import (
    AgentStage,
    AgentRunMode,
    AgentRunState,
    ProductInput,
)


def test_agent_stage_order_contains_generation_flow():
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


def test_agent_run_state_defaults_to_mock_mode():
    state = AgentRunState(project_id="project-1", product_input=ProductInput(product_name="테스트 상품"))
    assert state.mode == AgentRunMode.MOCK
    assert state.current_stage == AgentStage.INPUT_ROUTER
    assert state.errors == []
    assert state.cost_approval_status == "not_required"
    assert state.provider_trace == []
