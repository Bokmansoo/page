import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from src.api.auth import get_current_user_and_workspace
from src.db.database import get_db
from src.db.models import ProductProject, AuditLog, JobStatus, Brand
from src.services.validation import validate_external_url

router = APIRouter(prefix="/projects", tags=["projects"])


# Pydantic Schemas
class ProjectCreateSchema(BaseModel):
    name: str
    brand_id: str
    raw_input_url: Optional[str] = None
    raw_input_text: Optional[str] = None


class ProjectUpdateSchema(BaseModel):
    name: Optional[str] = None
    raw_input_text: Optional[str] = None
    status: Optional[str] = None
    current_step: Optional[str] = None


class ProjectResponseSchema(BaseModel):
    id: str
    workspace_id: str
    brand_id: str
    name: str
    status: str
    current_step: str
    raw_input_url: Optional[str]
    raw_input_text: Optional[str]
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class JobStatusSchema(BaseModel):
    project_id: str
    status: str
    error_message: Optional[str]
    updated_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


@router.get("", response_model=List[ProjectResponseSchema])
def list_projects(
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    return db.query(ProductProject).filter(ProductProject.workspace_id == workspace.id).all()


@router.post("", response_model=ProjectResponseSchema, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreateSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    user = auth_ctx["user"]
    workspace = auth_ctx["workspace"]

    # Validate brand exists in workspace
    brand = db.query(Brand).filter(Brand.id == payload.brand_id, Brand.workspace_id == workspace.id).first()
    if not brand:
        raise HTTPException(status_code=400, detail="Invalid brand_id for this workspace")

    # Validate URL if provided (SSRF check)
    if payload.raw_input_url:
        try:
            validate_external_url(payload.raw_input_url)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid URL: {str(e)}")

    # Create project
    project = ProductProject(
        workspace_id=workspace.id,
        brand_id=payload.brand_id,
        name=payload.name,
        raw_input_url=payload.raw_input_url,
        raw_input_text=payload.raw_input_text,
        status="processing" if payload.raw_input_url else "draft",
        current_step="raw_input"
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    # Write Audit Log
    log = AuditLog(
        workspace_id=workspace.id,
        user_id=user.id,
        action="project_created",
        entity_type="project",
        entity_id=project.id,
        payload={"name": project.name, "has_url": bool(project.raw_input_url)}
    )
    db.add(log)

    # Initialize Job Status if url exists
    if payload.raw_input_url:
        job = JobStatus(
            project_id=project.id,
            status="pending",
            error_message=None
        )
        db.add(job)

    db.commit()
    return project


@router.get("/{project_id}", response_model=ProjectResponseSchema)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    project = db.query(ProductProject).filter(
        ProductProject.id == project_id,
        ProductProject.workspace_id == workspace.id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectResponseSchema)
def update_project(
    project_id: str,
    payload: ProjectUpdateSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    user = auth_ctx["user"]
    workspace = auth_ctx["workspace"]
    project = db.query(ProductProject).filter(
        ProductProject.id == project_id,
        ProductProject.workspace_id == workspace.id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Update fields
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(project, key, value)

    # Log updates
    log = AuditLog(
        workspace_id=workspace.id,
        user_id=user.id,
        action="project_updated",
        entity_type="project",
        entity_id=project.id,
        payload=update_data
    )
    db.add(log)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}/status", response_model=JobStatusSchema)
def get_project_job_status(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    # Check project exists
    project = db.query(ProductProject).filter(
        ProductProject.id == project_id,
        ProductProject.workspace_id == workspace.id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    job = db.query(JobStatus).filter(JobStatus.project_id == project_id).order_by(JobStatus.updated_at.desc()).first()
    if not job:
        # Return a mock static job indicating no active extraction
        return JobStatus(
            project_id=project_id,
            status="completed",
            error_message=None,
            updated_at=project.updated_at
        )
    return job
