"""TASK-12.10 public, seller-facing promotion and quality-status endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from src.api.auth import get_current_user_and_workspace
from src.db.database import get_db
from src.services.quality_promotion_service import (
    QualityPromotionGateError,
    promote_current_quality_page,
    quality_status_projection,
)


router = APIRouter(tags=["Quality promotion"])


class PromoteCurrentPageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    detail_page_version_id: str | None = None


class QualityPromotionResponse(BaseModel):
    promotion_id: str
    detail_page_version_id: str
    quality_report_id: str
    quality_bar_hash: str
    target_channels: list[str]
    status: str = "promoted"


def _project_scope_or_404(db: Session, *, project_id: str, workspace_id: str) -> None:
    from src.db.models import ProductProject
    if db.query(ProductProject).filter_by(id=project_id, workspace_id=workspace_id).one_or_none() is None:
        raise HTTPException(status_code=404, detail="Product project not found")


@router.get("/projects/{project_id}/quality-status")
def get_quality_status(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict[str, Any] = Depends(get_current_user_and_workspace),
):
    _project_scope_or_404(db, project_id=project_id, workspace_id=auth_ctx["workspace"].id)
    try:
        return quality_status_projection(db, workspace_id=auth_ctx["workspace"].id, project_id=project_id)
    except QualityPromotionGateError as exc:
        raise HTTPException(status_code=409, detail={"code": "quality_gate_blocked", "message": str(exc)}) from exc


@router.post("/projects/{project_id}/page/promotion", response_model=QualityPromotionResponse, status_code=status.HTTP_201_CREATED)
def promote_current_page(
    project_id: str,
    payload: PromoteCurrentPageRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict[str, Any] = Depends(get_current_user_and_workspace),
):
    role = auth_ctx.get("role") or "owner"
    if role not in {"owner", "admin", "member", "editor"}:
        raise HTTPException(status_code=403, detail="Access denied: insufficient workspace permission")
    _project_scope_or_404(db, project_id=project_id, workspace_id=auth_ctx["workspace"].id)
    try:
        promotion = promote_current_quality_page(
            db, workspace_id=auth_ctx["workspace"].id, project_id=project_id,
            actor_id=auth_ctx["user"].id, requested_page_id=payload.detail_page_version_id,
        )
        db.commit()
        return QualityPromotionResponse(
            promotion_id=promotion.id, detail_page_version_id=promotion.detail_page_version_id,
            quality_report_id=promotion.quality_report_id, quality_bar_hash=promotion.quality_bar_hash,
            target_channels=sorted(promotion.target_channels_json or []),
        )
    except QualityPromotionGateError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "quality_gate_blocked", "message": str(exc)}) from exc
