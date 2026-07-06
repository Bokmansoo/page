import datetime
from typing import List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from src.api.auth import get_current_user_and_workspace
from src.db.database import get_db
from src.db.models import ProductProject, AuditLog, JobStatus, Brand, Asset
from src.services.validation import validate_external_url
from src.services.visual_background_service import VisualBackgroundService
from src.services.product_intake_service import ProductIntakeInput, normalize_intake_input
from src.services.product_understanding_service import generate_understanding_summary, ProductUnderstandingResponse
from src.services.sales_strategy_service import (
    SalesStrategyConfirmationRequest,
    SalesStrategyResponse,
    generate_sales_strategy,
    map_sales_direction_to_style,
)

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


class CategoryUpdateSchema(BaseModel):
    category: Literal["Fashion", "Beauty", "Food", "Living"]
    confirmed: bool = True


class AssetResponseSchema(BaseModel):
    id: str
    project_id: str
    source_type: str
    filename: str
    file_path: str
    mime_type: str
    file_size: int

    model_config = ConfigDict(from_attributes=True)


class ProjectResponseSchema(BaseModel):
    id: str
    workspace_id: str
    brand_id: str
    name: str
    status: str
    current_step: str
    category: Optional[str]
    category_confirmed: bool
    raw_input_url: Optional[str]
    raw_input_text: Optional[str]
    selected_background: Optional[str] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    assets: List[AssetResponseSchema] = []

    model_config = ConfigDict(from_attributes=True)


class JobStatusSchema(BaseModel):
    project_id: str
    status: str
    error_message: Optional[str]
    updated_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class BackgroundCandidateSchema(BaseModel):
    id: str
    title: str
    description: str
    palette: List[str]
    style_key: str
    safety_note: str

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
    role = auth_ctx.get("role") or "owner"

    if role not in ["owner", "admin", "member"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Insufficient permissions for this workspace"
        )

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


@router.patch("/{project_id}/category", response_model=ProjectResponseSchema)
def update_project_category(
    project_id: str,
    payload: CategoryUpdateSchema,
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

    project.category = payload.category
    project.category_confirmed = payload.confirmed
    project.category_confirmed_by = user.id if payload.confirmed else None
    project.category_confirmed_at = datetime.datetime.utcnow() if payload.confirmed else None
    project.current_step = "facts_verification"

    log = AuditLog(
        workspace_id=workspace.id,
        user_id=user.id,
        action="project_category_updated",
        entity_type="project",
        entity_id=project.id,
        payload={
            "category": payload.category,
            "confirmed": payload.confirmed,
        }
    )
    db.add(log)
    db.commit()
    db.refresh(project)
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


@router.post("/{project_id}/visual-backgrounds/generate", response_model=List[BackgroundCandidateSchema])
def generate_visual_backgrounds(
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

    service = VisualBackgroundService()
    candidates = service.get_candidates(project.name, project.category)
    return candidates


@router.post("/{project_id}/visual-backgrounds/{candidate_id}/select", response_model=ProjectResponseSchema)
def select_visual_background(
    project_id: str,
    candidate_id: str,
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

    valid_ids = ["cooling-blue", "minimal-white", "lifestyle-summer"]
    if candidate_id not in valid_ids:
        raise HTTPException(status_code=400, detail="Invalid background candidate ID")

    project.selected_background = candidate_id
    db.commit()
    db.refresh(project)

    log = AuditLog(
        workspace_id=workspace.id,
        user_id=user.id,
        action="project_background_selected",
        entity_type="project",
        entity_id=project.id,
        payload={"selected_background": candidate_id}
    )
    db.add(log)
    db.commit()

    return project


class ProjectAssetResponse(BaseModel):
    id: str
    project_id: str
    source_type: str
    filename: str
    file_path: str
    mime_type: str
    file_size: int

    model_config = ConfigDict(from_attributes=True)


@router.get("/{project_id}/assets", response_model=List[ProjectAssetResponse])
def list_project_assets(
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

    from src.db.models import Asset
    assets = db.query(Asset).filter(Asset.project_id == project_id).all()
    return assets


@router.post("/{project_id}/intake", response_model=ProjectResponseSchema)
def submit_project_intake(
    project_id: str,
    payload: ProductIntakeInput,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    user = auth_ctx["user"]
    project = db.query(ProductProject).filter(
        ProductProject.id == project_id,
        ProductProject.workspace_id == workspace.id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        normalized = normalize_intake_input(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    for url in normalized.urls + normalized.reference_urls + normalized.competitor_urls:
        try:
            validate_external_url(url)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid URL: {str(e)}")

    # Update project properties
    if normalized.description:
        project.raw_input_text = normalized.description
    if normalized.urls:
        project.raw_input_url = normalized.urls[0]

    # Store intake in its own metadata field so style_candidates_snapshot remains
    # a list reserved for downstream style candidate generation.
    snapshot = project.intake_snapshot or {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    snapshot["intake"] = normalized.model_dump()
    project.intake_snapshot = snapshot

    # Accept only assets already uploaded to this project/workspace. Intake must
    # never move an asset out of another project.
    if normalized.asset_ids:
        db_assets = db.query(Asset).filter(
            Asset.id.in_(normalized.asset_ids),
            Asset.project_id == project.id,
        ).all()
        found_asset_ids = {asset.id for asset in db_assets}
        missing_asset_ids = [asset_id for asset_id in normalized.asset_ids if asset_id not in found_asset_ids]
        if missing_asset_ids:
            raise HTTPException(status_code=400, detail=f"Invalid asset_ids: {', '.join(missing_asset_ids)}")

    db.commit()
    db.refresh(project)

    # Log action
    log = AuditLog(
        workspace_id=workspace.id,
        user_id=user.id,
        action="project_intake_submitted",
        entity_type="project",
        entity_id=project.id,
        payload={"intake": normalized.model_dump()}
    )
    db.add(log)
    db.commit()

    return project


@router.get("/{project_id}/understanding", response_model=ProductUnderstandingResponse)
def get_project_understanding(
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

    return generate_understanding_summary(project, db)


@router.post("/{project_id}/understanding/confirm", response_model=ProjectResponseSchema)
def confirm_project_understanding(
    project_id: str,
    payload: ProductUnderstandingResponse,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    user = auth_ctx["user"]
    project = db.query(ProductProject).filter(
        ProductProject.id == project_id,
        ProductProject.workspace_id == workspace.id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    snapshot = project.intake_snapshot or {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    snapshot["confirmed_understanding"] = payload.model_dump()
    project.intake_snapshot = snapshot

    log = AuditLog(
        workspace_id=workspace.id,
        user_id=user.id,
        action="project_understanding_confirmed",
        entity_type="project",
        entity_id=project.id,
        payload={"confirmed_understanding": payload.model_dump()}
    )
    db.add(log)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}/sales-strategy", response_model=SalesStrategyResponse)
def get_project_sales_strategy(
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

    return generate_sales_strategy(project, db)


@router.post("/{project_id}/sales-strategy/confirm", response_model=ProjectResponseSchema)
def confirm_project_sales_strategy(
    project_id: str,
    payload: SalesStrategyConfirmationRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    workspace = auth_ctx["workspace"]
    user = auth_ctx["user"]
    project = db.query(ProductProject).filter(
        ProductProject.id == project_id,
        ProductProject.workspace_id == workspace.id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    asset_filenames = {asset.filename for asset in project.assets}
    invalid_images = [name for name in payload.image_selection if name not in asset_filenames]
    if invalid_images:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid image_selection: {', '.join(invalid_images)}",
        )

    snapshot = dict(project.intake_snapshot) if isinstance(project.intake_snapshot, dict) else {}
    confirmed_strategy = payload.model_dump()
    confirmed_strategy["style_key"] = map_sales_direction_to_style(payload.selected_direction)
    snapshot["confirmed_sales_strategy"] = confirmed_strategy
    project.intake_snapshot = snapshot
    project.selected_style = confirmed_strategy["style_key"]

    db.add(AuditLog(
        workspace_id=workspace.id,
        user_id=user.id,
        action="project_sales_strategy_confirmed",
        entity_type="project",
        entity_id=project.id,
        payload={"confirmed_sales_strategy": confirmed_strategy},
    ))
    db.commit()
    db.refresh(project)
    return project
