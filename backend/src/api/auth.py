from fastapi import Header, Depends, HTTPException
from sqlalchemy.orm import Session
from src.db.database import get_db
from src.db.models import User, Workspace, Brand

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

    # Verify that the user owns the workspace or belongs to it (in Sprint 1, owner_id match)
    if workspace.owner_id != user.id:
        # For simplicity, if not owner, but it's a mock setup, we auto-assign or raise
        raise HTTPException(status_code=403, detail="Access denied to workspace")

    # 3. Bootstrap default Brand if none exists in workspace
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

    return {"user": user, "workspace": workspace}
