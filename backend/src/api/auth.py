"""Authorization dependency backed by Sprint 9 server sessions."""

import datetime
from typing import List

from fastapi import Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.database import get_db
from src.db.models import AiJobLog, ExportJob, ProductProject
from src.services.auth_service import (
    DEV_BRAND_ID as DEFAULT_BRAND_ID,
    DEV_USER_ID as DEFAULT_USER_ID,
    DEV_WORKSPACE_ID as DEFAULT_WORKSPACE_ID,
    get_auth_context,
)


def get_current_user_and_workspace(
    request: Request,
    response: Response,
    x_mock_user_id: str | None = Header(default=None, alias="X-Mock-User-Id"),
    x_mock_workspace_id: str | None = Header(default=None, alias="X-Mock-Workspace-Id"),
    db: Session = Depends(get_db),
):
    """Return the session user and active workspace.

    The legacy mock headers exist only for an explicitly enabled test fixture.
    They are ignored in normal development and production traffic.
    """
    return get_auth_context(
        db,
        request,
        response,
        test_mock_user_id=x_mock_user_id,
        test_mock_workspace_id=x_mock_workspace_id,
    )


def require_roles(allowed_roles: List[str]):
    def dependency(auth_ctx: dict = Depends(get_current_user_and_workspace)):
        role = auth_ctx.get("role") or "owner"
        # Older endpoints called the editable member role "member".
        effective_roles = {"member" if role == "editor" else role, role}
        if not effective_roles.intersection(allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: insufficient workspace permission",
            )
        return auth_ctx
    return dependency


def check_workspace_limits(db: Session, workspace_id: str):
    """Validates the workspace's development budget and hourly limits."""
    total_ai_cost = db.query(func.sum(AiJobLog.estimated_cost)).join(ProductProject).filter(
        ProductProject.workspace_id == workspace_id
    ).scalar() or 0.0
    if total_ai_cost >= 5.0:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="AI budget limit exceeded")

    one_hour_ago = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
    recent_ai_jobs = db.query(AiJobLog).join(ProductProject).filter(
        ProductProject.workspace_id == workspace_id,
        AiJobLog.created_at >= one_hour_ago,
    ).count()
    recent_exports = db.query(ExportJob).join(ProductProject).filter(
        ProductProject.workspace_id == workspace_id,
        ExportJob.created_at >= one_hour_ago,
    ).count()
    if recent_ai_jobs + recent_exports >= 10:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")
