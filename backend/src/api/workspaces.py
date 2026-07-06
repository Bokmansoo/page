import datetime
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from src.api.auth import get_current_user_and_workspace, require_roles
from src.db.database import get_db
from src.db.models import (
    Workspace, WorkspaceMember, WorkspaceInvitation, User, 
    AiJobLog, ExportJob, ProductProject, AuditLog
)

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])

# =====================================================================
# Request / Response Schemas
# =====================================================================

class WorkspaceUsageSchema(BaseModel):
    total_ai_cost: float
    ai_budget_limit: float
    recent_jobs_count_1h: int
    jobs_limit_1h: int
    is_blocked: bool

class MemberResponseSchema(BaseModel):
    user_id: str
    email: str
    name: str
    role: str
    joined_at: datetime.datetime

    class Config:
        from_attributes = True

class InviteCreateSchema(BaseModel):
    email: str = Field(..., description="초대받을 대상 이메일")
    role: str = Field("member", description="권한 역할 (admin, member, viewer)")

class InvitationResponseSchema(BaseModel):
    id: str
    workspace_id: str
    email: str
    role: str
    status: str
    created_at: datetime.datetime
    expires_at: datetime.datetime

    class Config:
        from_attributes = True

# =====================================================================
# API Endpoints
# =====================================================================

@router.get("/usage", response_model=WorkspaceUsageSchema)
def get_workspace_usage(
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]

    # 1. Total AI Cost
    total_ai_cost = db.query(func.sum(AiJobLog.estimated_cost)).join(ProductProject).filter(
        ProductProject.workspace_id == workspace.id
    ).scalar() or 0.0

    # 2. Hourly rate limiting stats
    one_hour_ago = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
    
    recent_ai_jobs = db.query(AiJobLog).join(ProductProject).filter(
        ProductProject.workspace_id == workspace.id,
        AiJobLog.created_at >= one_hour_ago
    ).count()
    
    recent_exports = db.query(ExportJob).join(ProductProject).filter(
        ProductProject.workspace_id == workspace.id,
        ExportJob.created_at >= one_hour_ago
    ).count()
    
    total_recent_jobs = recent_ai_jobs + recent_exports
    
    is_blocked = (total_ai_cost >= 5.0) or (total_recent_jobs >= 10)

    return WorkspaceUsageSchema(
        total_ai_cost=round(total_ai_cost, 4),
        ai_budget_limit=5.0,
        recent_jobs_count_1h=total_recent_jobs,
        jobs_limit_1h=10,
        is_blocked=is_blocked
    )


@router.get("/members", response_model=List[MemberResponseSchema])
def list_workspace_members(
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]

    # Retrieve owner
    owner = db.query(User).filter(User.id == workspace.owner_id).first()
    members_list = []
    if owner:
        members_list.append(MemberResponseSchema(
            user_id=owner.id,
            email=owner.email,
            name=owner.name,
            role="owner",
            joined_at=datetime.datetime.utcnow()
        ))

    # Retrieve other members from WorkspaceMember table
    memberships = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace.id
    ).all()

    for member in memberships:
        user = db.query(User).filter(User.id == member.user_id).first()
        if user:
            members_list.append(MemberResponseSchema(
                user_id=user.id,
                email=user.email,
                name=user.name,
                role=member.role,
                joined_at=member.joined_at
            ))

    return members_list


@router.post("/invitations", response_model=InvitationResponseSchema, status_code=status.HTTP_201_CREATED)
def invite_user(
    payload: InviteCreateSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(require_roles(["owner", "admin"]))
):
    user = auth_ctx["user"]
    workspace = auth_ctx["workspace"]

    if payload.role not in ["admin", "member", "viewer"]:
        raise HTTPException(status_code=400, detail="Invalid role type specified")

    # Check if target is already a member
    target_user = db.query(User).filter(User.email == payload.email).first()
    if target_user:
        if str(workspace.owner_id) == str(target_user.id):
            raise HTTPException(status_code=400, detail="User is already the owner of this workspace")
            
        existing_member = db.query(WorkspaceMember).filter(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == target_user.id
        ).first()
        if existing_member:
            raise HTTPException(status_code=400, detail="User is already a member of this workspace")

    # Create invitation
    invite = WorkspaceInvitation(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        email=payload.email,
        role=payload.role,
        status="pending",
        invited_by=user.id,
        expires_at=datetime.datetime.utcnow() + datetime.timedelta(days=7)
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    # Audit Log
    log = AuditLog(
        workspace_id=workspace.id,
        user_id=user.id,
        action="team_member_invited",
        entity_type="invitation",
        entity_id=invite.id,
        payload={"email": invite.email, "role": invite.role}
    )
    db.add(log)
    db.commit()

    return invite


@router.get("/invitations", response_model=List[InvitationResponseSchema])
def list_workspace_invitations(
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(require_roles(["owner", "admin"]))
):
    workspace = auth_ctx["workspace"]
    
    # Return active pending invitations
    return db.query(WorkspaceInvitation).filter(
        WorkspaceInvitation.workspace_id == workspace.id,
        WorkspaceInvitation.status == "pending"
    ).all()


@router.post("/invitations/{invite_id}/accept", status_code=status.HTTP_200_OK)
def accept_invitation(
    invite_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    user = auth_ctx["user"]
    
    invite = db.query(WorkspaceInvitation).filter(
        WorkspaceInvitation.id == invite_id,
        WorkspaceInvitation.status == "pending"
    ).first()

    if not invite:
        raise HTTPException(status_code=404, detail="Invitation not found or no longer active")

    # Ensure the current authenticated user's email matches the invite email
    # (or in mock environment, we allow matching or auto-mapping)
    if user.email.lower() != invite.email.lower():
        raise HTTPException(
            status_code=403, 
            detail=f"Access denied: This invitation is for {invite.email}, not {user.email}"
        )

    # Accept the invite
    invite.status = "accepted"
    
    # Create or update WorkspaceMember
    member = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == invite.workspace_id,
        WorkspaceMember.user_id == user.id
    ).first()
    
    if not member:
        member = WorkspaceMember(
            workspace_id=invite.workspace_id,
            user_id=user.id,
            role=invite.role,
            joined_at=datetime.datetime.utcnow()
        )
        db.add(member)
    else:
        member.role = invite.role

    # Audit Log
    log = AuditLog(
        workspace_id=invite.workspace_id,
        user_id=user.id,
        action="team_invitation_accepted",
        entity_type="membership",
        entity_id=user.id,
        payload={"invite_id": invite.id}
    )
    db.add(log)
    db.commit()

    return {"message": "Invitation accepted successfully", "workspace_id": invite.workspace_id}


@router.post("/invitations/{invite_id}/decline", status_code=status.HTTP_200_OK)
def decline_invitation(
    invite_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    user = auth_ctx["user"]
    
    invite = db.query(WorkspaceInvitation).filter(
        WorkspaceInvitation.id == invite_id,
        WorkspaceInvitation.status == "pending"
    ).first()

    if not invite:
        raise HTTPException(status_code=404, detail="Invitation not found or no longer active")

    if user.email.lower() != invite.email.lower():
        raise HTTPException(
            status_code=403, 
            detail=f"Access denied: This invitation is for {invite.email}, not {user.email}"
        )

    # Decline the invite
    invite.status = "declined"
    db.commit()

    return {"message": "Invitation declined successfully"}
