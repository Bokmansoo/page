from backend.src.agents.state import (
    AgentStage,
    AgentRunMode,
    AgentRunState,
    ProductInput,
)


def test_agent_stage_order_contains_generation_flow():
    assert [stage.value for stage in AgentStage] == [
        "intake",
        "product_understanding",
        "missing_info_check",
        "sales_strategy",
        "user_strategy_confirmation",
        "page_planning",
        "copy_generation",
        "visual_planning",
        "image_cost_approval",
        "image_generation",
        "image_review",
        "page_assembly",
        "qa_review",
        "review_editor",
        "export_package",
    ]


def test_agent_run_state_defaults_to_mock_mode():
    state = AgentRunState(project_id="project-1", product_input=ProductInput(product_name="테스트 상품"))
    assert state.mode == AgentRunMode.MOCK
    assert state.current_stage == AgentStage.INTAKE
    assert state.errors == []
    assert state.cost_approval_status == "not_required"
    assert state.provider_trace == []
