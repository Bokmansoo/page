import datetime
from typing import List
from fastapi import Header, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session
from src.db.database import get_db
from src.db.models import User, Workspace, Brand, WorkspaceMember, AiJobLog, ExportJob, ProductProject

DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-000000000002"
DEFAULT_BRAND_ID = "00000000-0000-0000-0000-000000000003"


def get_current_user_and_workspace(
    x_mock_user_id: str = Header(default=DEFAULT_USER_ID),
    x_mock_workspace_id: str = Header(default=DEFAULT_WORKSPACE_ID),
    db: Session = Depends(get_db)
):
    """
    Mock authentication dependency. Bootstraps user, workspace, and brand if they do not exist
    in order to support seamless local development and automated testing.
    Now supports multi-member workspaces and RBAC roles.
    """
    # 1. Bootstrap User
    user = db.query(User).filter(User.id == x_mock_user_id).first()
    if not user:
        user = User(id=x_mock_user_id, email=f"seller-{x_mock_user_id}@sellform.local", name="Default Seller")
        db.add(user)
        try:
            db.commit()
            db.refresh(user)
        except Exception:
            db.rollback()
            user = db.query(User).filter(User.id == x_mock_user_id).first()

    # 2. Bootstrap Workspace
    assert user is not None
    workspace = db.query(Workspace).filter(Workspace.id == x_mock_workspace_id).first()
    if not workspace:
        workspace = Workspace(id=x_mock_workspace_id, name="My Workspace", owner_id=user.id)
        db.add(workspace)
        try:
            db.commit()
            db.refresh(workspace)
        except Exception:
            db.rollback()
            workspace = db.query(Workspace).filter(Workspace.id == x_mock_workspace_id).first()

    assert workspace is not None

    # 3. Determine User's Role in this Workspace
    role = None
    if str(workspace.owner_id) == str(user.id):
        role = "owner"
    else:
        # Check WorkspaceMember relationship
        member = db.query(WorkspaceMember).filter(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == user.id
        ).first()
        if not member:
            raise HTTPException(status_code=403, detail="Access denied to workspace: Not a member")
        role = member.role

    # 4. Bootstrap default Brand if none exists in workspace
    brand = db.query(Brand).filter(Brand.workspace_id == workspace.id).first()
    if not brand:
        brand = Brand(
            id=DEFAULT_BRAND_ID,
            workspace_id=workspace.id,
            name="Default Brand",
            brand_colors={"primary": "#4F46E5", "secondary": "#10B981"},
            font_tone="modern",
            default_disclaimer="본 상품은 100% 정품이며 정식 세관 검사를 거쳤습니다."
        )
        db.add(brand)
        try:
            db.commit()
        except Exception:
            db.rollback()

    return {"user": user, "workspace": workspace, "role": role}


def require_roles(allowed_roles: List[str]):
    """
    Dependency that enforces a list of allowed roles for access.
    """
    def dependency(auth_ctx: dict = Depends(get_current_user_and_workspace)):
        role = auth_ctx.get("role") or "owner"
        if role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Insufficient permissions for this workspace"
            )
        return auth_ctx
    return dependency


def check_workspace_limits(db: Session, workspace_id: str):
    """
    Validates that the workspace has not exceeded its AI budget limit or Hourly Rate limit.
    """
    # 1. Budget Limit ($5.00)
    total_ai_cost = db.query(func.sum(AiJobLog.estimated_cost)).join(ProductProject).filter(
        ProductProject.workspace_id == workspace_id
    ).scalar() or 0.0
    
    if total_ai_cost >= 5.0:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="AI budget limit exceeded ($5.00). Please upgrade your workspace plan."
        )
        
    # 2. Hourly Rate Limit (10 jobs / hour)
    one_hour_ago = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
    
    recent_ai_jobs = db.query(AiJobLog).join(ProductProject).filter(
        ProductProject.workspace_id == workspace_id,
        AiJobLog.created_at >= one_hour_ago
    ).count()
    
    recent_exports = db.query(ExportJob).join(ProductProject).filter(
        ProductProject.workspace_id == workspace_id,
        ExportJob.created_at >= one_hour_ago
    ).count()
    
    total_recent_jobs = recent_ai_jobs + recent_exports
    if total_recent_jobs >= 10:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Workspaces are limited to 10 AI or Export jobs per hour."
        )

