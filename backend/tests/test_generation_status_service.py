import datetime
import uuid

import pytest

from src.db.models import (
    AgentRun,
    AgentRunStep,
    ExportJob,
    ImageGenerationJobRecord,
    ProductProject,
    User,
    Workspace,
    Brand,
)
from src.services.generation_status_service import GenerationStatusService, seller_guidance


@pytest.fixture
def test_user(db_session):
    user = User(
        id=str(uuid.uuid4()),
        email="test@example.com",
        name="Test User",
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def test_workspace(db_session, test_user):
    ws = Workspace(
        id=str(uuid.uuid4()),
        name="Test Workspace",
        owner_id=test_user.id,
    )
    db_session.add(ws)
    db_session.flush()
    return ws


@pytest.fixture
def test_brand(db_session, test_workspace):
    brand = Brand(
        id=str(uuid.uuid4()),
        workspace_id=test_workspace.id,
        name="Test Brand",
        font_tone="modern",
    )
    db_session.add(brand)
    db_session.flush()
    return brand


def test_generation_status_running_when_agent_run_is_running(db_session, test_workspace, test_user, test_brand):
    project = ProductProject(
        workspace_id=test_workspace.id,
        brand_id=test_brand.id,
        name="루메나 휴대용 무선 냉각선풍기",
        status="processing",
        current_step="image_generation",
    )
    db_session.add(project)
    db_session.flush()

    run = AgentRun(
        id="run-running",
        workspace_id=test_workspace.id,
        project_id=project.id,
        mode="real",
        status="running",
        current_stage="image_generation",
        input_snapshot={},
        outputs_json={
            "provider_cost_projection": {
                "actual_cost_complete": False,
                "has_unknown_cost": True,
                "attempt_count": 3,
            },
        },
        estimated_cost=0.12,
        actual_cost=0.08,
        created_by=test_user.id,
    )
    db_session.add(run)
    db_session.add(
        AgentRunStep(
            run_id=run.id,
            stage="copywriting",
            status="completed",
            token_usage={"input_tokens": 1200, "output_tokens": 500},
            estimated_cost=0.02,
        )
    )
    db_session.commit()

    status = GenerationStatusService(db_session).get_project_status(project.id, test_workspace.id)

    assert status["state"] == "running"
    assert status["current_stage"] == "image_generation"
    assert status["can_start_new_run"] is False
    assert status["recommended_action"] == "view_status"
    assert status["cost"]["estimated"] == 0.12
    assert status["cost"]["actual"] == 0.08
    assert status["cost"]["actual_cost_complete"] is False
    assert status["cost"]["has_unknown_cost"] is True
    assert status["cost"]["provider_attempt_count"] == 3
    assert status["cost"]["token_input"] == 1200
    assert status["cost"]["token_output"] == 500


def test_generation_status_completed_when_project_has_page_and_no_active_jobs(db_session, test_workspace, test_user, test_brand):
    project = ProductProject(
        workspace_id=test_workspace.id,
        brand_id=test_brand.id,
        name="완료된 상세페이지",
        status="completed",
        current_step="review_editor",
    )
    db_session.add(project)
    db_session.flush()

    run = AgentRun(
        id="run-completed",
        workspace_id=test_workspace.id,
        project_id=project.id,
        mode="real",
        status="completed",
        current_stage="review_editor",
        input_snapshot={},
        outputs_json={},
        actual_cost=0.04,
        created_by=test_user.id,
        completed_at=datetime.datetime.utcnow(),
    )
    db_session.add(run)
    db_session.commit()

    status = GenerationStatusService(db_session).get_project_status(project.id, test_workspace.id)

    assert status["state"] == "completed"
    assert status["can_start_new_run"] is True
    assert status["recommended_action"] == "view_result"
    assert status["result_url"] == f"/workspace/projects/{project.id}/result"


def test_generation_status_failed_when_latest_agent_run_failed(db_session, test_workspace, test_user, test_brand):
    project = ProductProject(
        workspace_id=test_workspace.id,
        brand_id=test_brand.id,
        name="실패한 상세페이지",
        status="draft",
        current_step="copywriting",
    )
    db_session.add(project)
    db_session.flush()

    run = AgentRun(
        id="run-failed",
        workspace_id=test_workspace.id,
        project_id=project.id,
        mode="real",
        status="failed",
        current_stage="copywriting",
        input_snapshot={},
        outputs_json={},
        error_log=[{"stage": "copywriting", "message": "LLM provider timeout"}],
        created_by=test_user.id,
    )
    db_session.add(run)
    db_session.add(
        AgentRunStep(
            run_id=run.id,
            stage="copywriting",
            status="failed",
            error_message="LLM provider timeout",
        )
    )
    db_session.commit()

    status = GenerationStatusService(db_session).get_project_status(project.id, test_workspace.id)

    assert status["state"] == "failed"
    assert status["failed_stage"] == "copywriting"
    assert status["last_error"] == "GRAPH_STEP_FAILED"
    assert status["steps"][0]["error_message"] == "GRAPH_STEP_FAILED"
    assert status["recommended_action"] == "retry_failed_stage"
    assert status["seller_guidance"] == {
        "status": "failed",
        "safe_code": "GRAPH_STEP_FAILED",
        "cause_ko": "작업을 완료하지 못했습니다.",
        "action_ko": "원인을 확인한 뒤 같은 작업을 다시 시도하세요.",
        "action_type": "retry",
        "retryable": True,
        "review_required": False,
    }


def test_generation_status_replaces_unknown_error_text_with_bounded_korean_guidance(
    db_session, test_workspace, test_user, test_brand,
):
    project = ProductProject(
        workspace_id=test_workspace.id,
        brand_id=test_brand.id,
        name="bounded failure",
        status="draft",
        current_step="image_generation",
    )
    db_session.add(project)
    db_session.flush()
    run = AgentRun(
        id="run-raw-error-code",
        workspace_id=test_workspace.id,
        project_id=project.id,
        mode="real",
        status="failed",
        current_stage="image_generation",
        input_snapshot={},
        outputs_json={},
        error_log=[{"code": "PROMPT_SECRET_7F3A", "message": "https://signed.example/private?token=SECRET_TOKEN_9C2"}],
        created_by=test_user.id,
    )
    db_session.add(run)
    db_session.commit()

    status = GenerationStatusService(db_session).get_project_status(project.id, test_workspace.id)

    assert status["last_error"] == "GRAPH_EXECUTION_FAILED"
    assert status["seller_guidance"]["safe_code"] == "GRAPH_EXECUTION_FAILED"
    assert status["seller_guidance"]["cause_ko"] == "작업을 완료하지 못했습니다."
    assert status["seller_guidance"]["action_ko"] == "원인을 확인한 뒤 같은 작업을 다시 시도하세요."
    assert "PROMPT_SECRET_7F3A" not in repr(status)
    assert "SECRET_TOKEN_9C2" not in repr(status)


@pytest.mark.parametrize(
    ("state", "code", "review_stage", "action_type", "retryable", "review_required"),
    [
        ("completed", None, None, "view_result", False, False),
        ("failed", "PROVIDER_TIMEOUT", None, "retry", True, False),
        ("failed", "PROVIDER_OUTCOME_UNKNOWN", None, "refresh_status", False, False),
        ("needs_review", None, None, "review", False, True),
        ("awaiting_review", None, "seller_confirmation", "confirm_details", False, True),
    ],
)
def test_seller_guidance_covers_progress_failure_recovery_and_review(
    state, code, review_stage, action_type, retryable, review_required,
):
    guidance = seller_guidance(state, code=code, review_stage=review_stage)

    assert guidance["action_type"] == action_type
    assert guidance["retryable"] is retryable
    assert guidance["review_required"] is review_required
    assert guidance["cause_ko"] and guidance["action_ko"]
    assert "provider_wait" not in repr(guidance)


def test_generation_status_waiting_when_image_cost_approval_is_required(db_session, test_workspace, test_user, test_brand):
    project = ProductProject(
        workspace_id=test_workspace.id,
        brand_id=test_brand.id,
        name="이미지 승인 대기",
        status="processing",
        current_step="image_generation",
    )
    db_session.add(project)
    db_session.flush()

    db_session.add(
        ImageGenerationJobRecord(
            project_id=project.id,
            job_id="image-job-1",
            section_id="hero",
            role="hero",
            prompt="상품 이미지 생성",
            status="awaiting_cost_approval",
        )
    )
    db_session.commit()

    status = GenerationStatusService(db_session).get_project_status(project.id, test_workspace.id)

    assert status["state"] == "waiting_for_cost_approval"
    assert status["can_start_new_run"] is False
    assert status["recommended_action"] == "approve_cost_or_continue_mock"
    assert status["image_jobs"]["total"] == 1
    assert status["image_jobs"]["awaiting_cost_approval"] == 1


def test_generation_status_running_when_export_job_is_running(db_session, test_workspace, test_user, test_brand):
    project = ProductProject(
        workspace_id=test_workspace.id,
        brand_id=test_brand.id,
        name="export 진행 중",
        status="completed",
        current_step="export",
    )
    db_session.add(project)
    db_session.flush()
    db_session.add(
        ExportJob(
            project_id=project.id,
            preset_name="smartstore",
            status="running",
            created_by=test_user.id,
        )
    )
    db_session.commit()

    status = GenerationStatusService(db_session).get_project_status(project.id, test_workspace.id)

    assert status["state"] == "running"
    assert status["current_stage"] == "export"
    assert status["can_start_new_run"] is False
    assert status["export_jobs"]["latest_status"] == "running"
