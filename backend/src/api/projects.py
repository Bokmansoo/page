import datetime
from typing import Dict, List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session
from src.api.auth import get_current_user_and_workspace
from src.db.database import get_db
from src.db.models import AssetInspectionRecord, ProductProject, AuditLog, JobStatus, Brand, Asset, ExportJob, AgentRun, SourceCapture
from src.schemas.project_worklist import ProjectWorklistItem, ProjectWorklistResponse
from src.services.validation import validate_external_url
from src.services.brand_kit_service import snapshot_project_brand_kit
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
    usage_status: str
    filename: str
    mime_type: str
    file_size: int
    intake_order: Optional[int] = None
    source_asset_id: Optional[str] = None
    cutout_status: Optional[str] = None
    background_removed: bool = False
    product_identity_preserved: bool = True
    asset_role: str = "unknown"
    role_confidence: float = 0.0
    role_source: str = "auto"
    quality_status: str = "warning"
    identity_status: str = "needs_review"
    width: Optional[int] = None
    height: Optional[int] = None
    image_format: Optional[str] = None
    quality_warnings: List[str] = Field(default_factory=list)
    safe_crop_status: str = "needs_review"
    is_representative: bool = False
    representative_source: str = "auto"
    classification_version: int = 0

    @field_validator("quality_warnings", mode="before")
    @classmethod
    def normalize_legacy_quality_warnings(cls, value):
        # Older imported assets may predate the non-null JSON default. Keep
        # project listing compatible without mutating the persisted evidence.
        return value or []

    model_config = ConfigDict(from_attributes=True)


class SourceCaptureResponseSchema(BaseModel):
    id: str
    project_id: str
    platform: str
    source_role: str
    collection_status: str
    failure_code: Optional[str] = None
    collected_image_count: int
    collected_spec_count: int
    attempted_at: datetime.datetime

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
    selected_background: Optional[str] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    assets: List[AssetResponseSchema] = Field(default_factory=list)

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


def _normalize_worklist_status(project: ProductProject) -> str:
    status = (project.status or "").lower()
    if status in {"completed", "needs_review", "failed", "generating"}:
        return status
    if project.pages:
        return "completed"
    if status in {"draft", "processing", "checking", "running", "pending"}:
        return "generating"
    if status in {"ready", "review", "reviewing"}:
        return "needs_review"
    return "generating"


def _thumbnail_url_from_job(job: ExportJob | None) -> str | None:
    if not job or not job.output_images:
        return None
    first_image = job.output_images[0]
    if not isinstance(first_image, str):
        return None
    if "/page/export/download/" in first_image or first_image.startswith("/api/"):
        return None
    return first_image


def _to_worklist_item(
    project: ProductProject,
    latest_export_job: ExportJob | None,
    run_id: str | None = None
) -> ProjectWorklistItem:
    project_id = str(project.id)
    status_value = _normalize_worklist_status(project)
    return ProjectWorklistItem(
        project_id=project_id,
        project_name=project.name,
        status=status_value,
        thumbnail_url=_thumbnail_url_from_job(latest_export_job),
        result_url=f"/workspace/projects/{project_id}/result",
        review_url=f"/workspace/projects/{project_id}/page-editor?mode=review",
        export_history_url=f"/workspace/exports?project_id={project_id}",
        last_export_status=latest_export_job.status if latest_export_job else None,
        run_id=run_id,
        updated_at=project.updated_at.isoformat() if project.updated_at else "",
    )


@router.get("/worklist", response_model=ProjectWorklistResponse)
def list_project_worklist(
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    workspace = auth_ctx["workspace"]
    projects = (
        db.query(ProductProject)
        .filter(ProductProject.workspace_id == workspace.id)
        .order_by(ProductProject.updated_at.desc())
        .limit(100)
        .all()
    )

    items = []
    for project in projects:
        latest_export_job = (
            db.query(ExportJob)
            .filter(ExportJob.project_id == project.id)
            .order_by(ExportJob.created_at.desc())
            .first()
        )
        latest_run = (
            db.query(AgentRun)
            .filter(AgentRun.project_id == project.id)
            .order_by(AgentRun.created_at.desc())
            .first()
        )
        run_id_val = str(latest_run.id) if latest_run else None
        items.append(_to_worklist_item(project, latest_export_job, run_id_val))
    return ProjectWorklistResponse(items=items)


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
    db.flush()
    snapshot_project_brand_kit(db, project)
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
    usage_status: str
    filename: str
    file_path: str
    mime_type: str
    file_size: int
    source_asset_id: Optional[str] = None
    cutout_status: Optional[str] = None
    background_removed: bool = False
    product_identity_preserved: bool = True
    asset_role: str = "unknown"
    role_confidence: float = 0.0
    role_source: str = "auto"
    quality_status: str = "warning"
    identity_status: str = "needs_review"
    width: Optional[int] = None
    height: Optional[int] = None
    image_format: Optional[str] = None
    quality_warnings: List[str] = []
    ocr_text: Optional[str] = None
    safe_crop_status: str = "needs_review"
    is_representative: bool = False
    representative_source: str = "auto"
    classification_version: int = 0
    # LG-12I photo-only intake sends an immutable asset reference. Expose the
    # persisted digest so clients never need to invent one after upload.
    content_hash: Optional[str] = None

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
    from src.services.image_asset_inspector import backfill_project_asset_metadata
    backfill_project_asset_metadata(project_id, db)
    assets = db.query(Asset).filter(Asset.project_id == project_id).all()
    return assets


@router.get("/{project_id}/source-captures", response_model=List[SourceCaptureResponseSchema])
def list_project_source_captures(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Show URL collection attempts, including normal access-limited outcomes."""
    workspace = auth_ctx["workspace"]
    project = db.query(ProductProject).filter(
        ProductProject.id == project_id,
        ProductProject.workspace_id == workspace.id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return (
        db.query(SourceCapture)
        .filter(SourceCapture.project_id == project.id)
        .order_by(SourceCapture.attempted_at.asc())
        .all()
    )


class AssetClassificationUpdate(BaseModel):
    asset_role: Optional[Literal[
        "product_main",
        "product_detail",
        "product_component",
        "product_in_use",
        "feature",
        "usage_scene",
        "components",
        "material_detail",
        "package",
        "shipping_info",
        "spec_reference",
        "supplier_banner",
        "decorative",
        "unidentifiable_reference",
        "unknown",
    ]] = None
    is_representative: Optional[bool] = None


class AssetInspectionResponse(BaseModel):
    id: str
    project_id: str
    asset_id: str
    analysis_version: int
    status: Literal["pending", "completed", "failed"]
    analyzer_version: str
    asset_role: Optional[str] = None
    rights_status: Optional[str] = None
    final_output_eligible: bool = False
    duplicate_asset_ids: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    ocr_blocks: List[dict] = Field(default_factory=list)
    translation_blocks: List[dict] = Field(default_factory=list)
    numeric_evidence: List[str] = Field(default_factory=list)
    analysis_metadata: dict = Field(default_factory=dict)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime.datetime
    completed_at: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AssetInspectionRunRequest(BaseModel):
    asset_ids: Optional[List[str]] = None


class AssetInspectionReviewRequest(BaseModel):
    translated_text_by_index: Dict[int, str] = Field(default_factory=dict)
    confirm_identity: bool = False


class AssetUnderstandingReadinessResponse(BaseModel):
    ready: bool
    blockers: List[dict] = Field(default_factory=list)


def _project_or_404(project_id: str, workspace_id: str, db: Session) -> ProductProject:
    project = db.query(ProductProject).filter(
        ProductProject.id == project_id,
        ProductProject.workspace_id == workspace_id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/{project_id}/asset-inspections", response_model=List[AssetInspectionResponse])
def list_asset_inspections(
    project_id: str,
    include_history: bool = False,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Show the latest analysis state (or history) for the Sprint 2 asset board."""
    _project_or_404(project_id, auth_ctx["workspace"].id, db)
    if include_history:
        return (
            db.query(AssetInspectionRecord)
            .filter(AssetInspectionRecord.project_id == project_id)
            .order_by(AssetInspectionRecord.asset_id, AssetInspectionRecord.analysis_version.desc())
            .all()
        )
    from src.services.asset_understanding_service import latest_asset_inspections
    return latest_asset_inspections(project_id, db)


@router.post(
    "/{project_id}/asset-inspections",
    response_model=List[AssetInspectionResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_asset_inspections(
    project_id: str,
    payload: AssetInspectionRunRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Run a non-destructive classification/OCR-evidence pass for image assets."""
    _project_or_404(project_id, auth_ctx["workspace"].id, db)
    if payload.asset_ids:
        found = {
            asset.id for asset in db.query(Asset).filter(
                Asset.project_id == project_id, Asset.id.in_(payload.asset_ids)
            ).all()
        }
        missing = set(payload.asset_ids) - found
        if missing:
            raise HTTPException(status_code=404, detail="Asset not found in project")
    from src.services.asset_understanding_service import run_project_asset_inspections
    records = run_project_asset_inspections(project_id, db, payload.asset_ids)
    db.add(AuditLog(
        workspace_id=auth_ctx["workspace"].id,
        user_id=auth_ctx["user"].id,
        action="asset_inspection_requested",
        entity_type="project",
        entity_id=project_id,
        payload={"asset_ids": payload.asset_ids or "all", "record_count": len(records)},
    ))
    db.commit()
    for record in records:
        db.refresh(record)
    return records


@router.post(
    "/{project_id}/assets/{asset_id}/asset-inspections/retry",
    response_model=AssetInspectionResponse,
    status_code=status.HTTP_201_CREATED,
)
def retry_asset_inspection(
    project_id: str,
    asset_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Create a fresh analysis version for one asset without erasing history."""
    _project_or_404(project_id, auth_ctx["workspace"].id, db)
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.project_id == project_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    from src.services.asset_understanding_service import run_asset_inspection
    record = run_asset_inspection(asset, db)
    db.add(AuditLog(
        workspace_id=auth_ctx["workspace"].id,
        user_id=auth_ctx["user"].id,
        action="asset_inspection_retried",
        entity_type="asset",
        entity_id=asset.id,
        payload={"analysis_version": record.analysis_version},
    ))
    db.commit()
    db.refresh(record)
    return record


@router.patch(
    "/{project_id}/assets/{asset_id}/asset-inspections/{inspection_id}/review",
    response_model=AssetInspectionResponse,
    status_code=status.HTTP_201_CREATED,
)
def review_asset_inspection_result(
    project_id: str,
    asset_id: str,
    inspection_id: str,
    payload: AssetInspectionReviewRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Save seller-confirmed identity/translation as a new immutable version."""
    _project_or_404(project_id, auth_ctx["workspace"].id, db)
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.project_id == project_id).first()
    current = db.query(AssetInspectionRecord).filter(
        AssetInspectionRecord.id == inspection_id,
        AssetInspectionRecord.asset_id == asset_id,
        AssetInspectionRecord.project_id == project_id,
    ).first()
    if not asset or not current:
        raise HTTPException(status_code=404, detail="Asset inspection not found")
    from src.services.asset_understanding_service import review_asset_inspection
    try:
        record = review_asset_inspection(
            asset,
            current,
            db,
            translated_text_by_index=payload.translated_text_by_index,
            confirm_identity=payload.confirm_identity,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.add(AuditLog(
        workspace_id=auth_ctx["workspace"].id,
        user_id=auth_ctx["user"].id,
        action="asset_inspection_seller_reviewed",
        entity_type="asset",
        entity_id=asset.id,
        payload={
            "analysis_version": record.analysis_version,
            "translation_indexes": sorted(payload.translated_text_by_index),
            "confirm_identity": payload.confirm_identity,
        },
    ))
    db.commit()
    db.refresh(record)
    return record


@router.get(
    "/{project_id}/asset-understanding-readiness",
    response_model=AssetUnderstandingReadinessResponse,
)
def get_asset_understanding_readiness(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    project = _project_or_404(project_id, auth_ctx["workspace"].id, db)
    input_bundle = (project.intake_snapshot or {}).get("input_bundle") or {}
    from src.services.asset_understanding_service import project_asset_understanding_blockers
    blockers = project_asset_understanding_blockers(
        project_id,
        db,
        asset_ids=input_bundle.get("asset_ids") or None,
    )
    return {"ready": not blockers, "blockers": blockers}


@router.patch("/{project_id}/assets/{asset_id}/classification", response_model=ProjectAssetResponse)
def update_asset_classification(
    project_id: str,
    asset_id: str,
    payload: AssetClassificationUpdate,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Apply a seller-selected image role; manual choices outrank auto hints."""
    workspace = auth_ctx["workspace"]
    project = db.query(ProductProject).filter(
        ProductProject.id == project_id,
        ProductProject.workspace_id == workspace.id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.project_id == project_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    if payload.asset_role is not None:
        asset.asset_role = payload.asset_role
        asset.role_confidence = 1.0
        asset.role_source = "manual"
    if payload.is_representative is True:
        for project_asset in db.query(Asset).filter(Asset.project_id == project_id).all():
            project_asset.is_representative = project_asset.id == asset.id
            if project_asset.id != asset.id and project_asset.representative_source == "manual":
                project_asset.representative_source = "auto"
        asset.is_representative = True
        asset.representative_source = "manual"
        asset.identity_status = "confirmed"
        # A confirmed representative is the product's primary visual by
        # definition.  Keep the two signals in sync even when the asset was
        # previously classified as a detail/package image.
        asset.asset_role = "product_main"
        asset.role_confidence = 1.0
        asset.role_source = "manual"
    elif payload.is_representative is False:
        asset.is_representative = False
        asset.representative_source = "auto"
        asset.identity_status = "needs_review"
    # Keep the latest inspection board consistent with the seller's manual
    # decision while preserving previous analysis versions.
    from src.services.asset_understanding_service import run_asset_inspection
    run_asset_inspection(asset, db)
    db.add(AuditLog(
        workspace_id=workspace.id,
        user_id=auth_ctx["user"].id,
        action="asset_visual_role_updated",
        entity_type="asset",
        entity_id=asset.id,
        payload={"asset_role": payload.asset_role, "is_representative": payload.is_representative},
    ))
    db.commit()
    db.refresh(asset)
    return asset


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
