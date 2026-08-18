"""LG-1 API for durable LangGraph run inspection and control."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from src.api.auth import get_current_user_and_workspace
from src.db.database import get_db
from src.db.models import AgentRun
from src.services.langgraph_run_service import (
    GraphRunCancelled,
    GraphRunExecutionFailed,
    GraphRunNotFound,
    GraphRunResumeUnavailable,
    GraphRunResumeRequired,
    GraphRunReviewRequired,
    GraphRunStateView,
    GraphRunThreadMismatch,
    LangGraphRunService,
)


router = APIRouter(prefix="/graph-runs", tags=["graph-runs"])


class GraphRunStateResponse(BaseModel):
    run_id: str
    thread_id: str
    status: str
    current_stage: str
    checkpoint_id: str | None = None
    values: dict[str, Any] = Field(default_factory=dict)
    next_nodes: list[str] = Field(default_factory=list)


class GraphRunResumeRequest(BaseModel):
    """LG-4 resume envelope; thread_id prevents cross-run resumes."""

    thread_id: str
    response: dict[str, Any]


class UnifiedProductIntakeRequest(BaseModel):
    """Reference-only request for the LG-12I production intake subgraph."""

    model_config = ConfigDict(extra="forbid")

    input_mode: str
    source_payload_refs: list[dict[str, Any]] = Field(default_factory=list)
    requested_generation_mode: str = "quick"
    target_channels: list[str] = Field(default_factory=list)


def _state_response(view: GraphRunStateView) -> GraphRunStateResponse:
    return GraphRunStateResponse(
        run_id=view.run_id,
        thread_id=view.thread_id,
        status=view.status,
        current_stage=view.current_stage,
        checkpoint_id=view.checkpoint_id,
        values=view.values,
        next_nodes=view.next_nodes,
    )


def _translate_error(error: ValueError) -> HTTPException:
    if isinstance(error, GraphRunNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, (GraphRunCancelled, GraphRunResumeUnavailable, GraphRunThreadMismatch)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, (GraphRunResumeRequired, GraphRunReviewRequired)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, GraphRunExecutionFailed):
        return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))


@router.post("/projects/{project_id}/unified-intake", response_model=GraphRunStateResponse, status_code=201)
def start_unified_product_intake(
    project_id: str,
    payload: UnifiedProductIntakeRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Enter all LG-12I modes through the same compiled LangGraph subgraph."""

    try:
        run = LangGraphRunService.start_unified_product_intake(
            project_id=project_id,
            workspace_id=auth_ctx["workspace"].id,
            actor_id=auth_ctx["user"].id,
            request=payload.model_dump(),
            db=db,
        )
        return _state_response(LangGraphRunService.get_state(run.id, auth_ctx["workspace"].id, db))
    except ValueError as error:
        raise _translate_error(error) from error


@router.post("/{run_id}/start", response_model=GraphRunStateResponse)
def start_graph_run(
    run_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    try:
        run = LangGraphRunService.start(run_id, auth_ctx["workspace"].id, db)
        return _state_response(LangGraphRunService.get_state(run.id, auth_ctx["workspace"].id, db))
    except ValueError as error:
        raise _translate_error(error) from error


@router.get("/projects/{project_id}/review", response_model=GraphRunStateResponse)
def get_project_pending_review(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Restore the latest seller-review interrupt or recoverable graph failure."""

    run = (
        db.query(AgentRun)
        .filter(
            AgentRun.project_id == project_id,
            AgentRun.workspace_id == auth_ctx["workspace"].id,
            AgentRun.status.in_(["awaiting_review", "failed"]),
        )
        .order_by(AgentRun.updated_at.desc(), AgentRun.created_at.desc())
        .first()
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No pending or recoverable graph run for this project.")
    try:
        return _state_response(LangGraphRunService.get_state(run.id, auth_ctx["workspace"].id, db))
    except ValueError as error:
        raise _translate_error(error) from error


@router.get("/{run_id}", response_model=GraphRunStateResponse)
def get_graph_run(
    run_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    try:
        return _state_response(LangGraphRunService.get_state(run_id, auth_ctx["workspace"].id, db))
    except ValueError as error:
        raise _translate_error(error) from error


@router.get("/{run_id}/history", response_model=list[GraphRunStateResponse])
def graph_run_history(
    run_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    try:
        return [
            _state_response(item)
            for item in LangGraphRunService.history(run_id, auth_ctx["workspace"].id, db)
        ]
    except ValueError as error:
        raise _translate_error(error) from error


@router.post("/{run_id}/cancel", response_model=GraphRunStateResponse)
def cancel_graph_run(
    run_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    try:
        run = LangGraphRunService.cancel(run_id, auth_ctx["workspace"].id, db)
        return _state_response(LangGraphRunService.get_state(run.id, auth_ctx["workspace"].id, db))
    except ValueError as error:
        raise _translate_error(error) from error


@router.post("/{run_id}/resume", response_model=GraphRunStateResponse)
def resume_graph_run(
    run_id: str,
    payload: GraphRunResumeRequest | None = None,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    try:
        run = LangGraphRunService.resume(
            run_id,
            auth_ctx["workspace"].id,
            db,
            thread_id=payload.thread_id if payload else None,
            resume_payload=payload.response if payload else None,
        )
        return _state_response(LangGraphRunService.get_state(run.id, auth_ctx["workspace"].id, db))
    except ValueError as error:
        raise _translate_error(error) from error
