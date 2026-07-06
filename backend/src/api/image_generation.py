from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.orm import Session

from src.db.database import get_db
from src.db.models import ProductPage, PageSection, Asset, ImageGenerationJobRecord
from src.api.auth import get_current_user_and_workspace
from src.api.pages import get_project_or_404
from src.services.image_generation_service import (
    get_or_create_job_record,
    execute_image_generation,
    sync_job_to_project_json
)

router = APIRouter(tags=["Image Generation"])


class GenerateImageRequest(BaseModel):
    cost_approved: bool = False


class RegenerateImageRequest(BaseModel):
    prompt: Optional[str] = None


class VisualJobResponseSchema(BaseModel):
    job_id: str
    section_id: str
    role: str
    source_asset_ids: List[str] = Field(default_factory=list)
    prompt: str
    negative_prompt: str = ""
    preserve_product_identity: bool = True
    output_size: str = "1024x1024"
    cost_tier: str = "standard"
    status: str
    provider: Optional[str] = None
    model: Optional[str] = None
    attempt_count: int = 0
    output_asset_id: Optional[str] = None
    error_code: Optional[str] = None
    warnings: Optional[List[str]] = None

    model_config = ConfigDict(from_attributes=True)


@router.post(
    "/projects/{project_id}/visual-jobs/{job_id}/generate",
    response_model=VisualJobResponseSchema,
    status_code=200
)
def generate_image_for_job(
    project_id: str,
    job_id: str,
    req: GenerateImageRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    # 1. Verify workspace and project scoping
    get_project_or_404(db, project_id, workspace.id)

    # 2. Run service execution
    try:
        record = execute_image_generation(
            project_id=project_id,
            job_id=job_id,
            db=db,
            cost_approved=req.cost_approved
        )
        return record
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except RuntimeError as e:
        # RuntimeErrors from provider represent handled runtime error codes
        # Still return 200 with the failed record status, or raise 500 depending on criteria.
        # Task 5 says: check endpoint scopes... let's return the record so client can inspect error_code.
        record = get_or_create_job_record(project_id, job_id, db)
        return record


@router.get(
    "/projects/{project_id}/visual-jobs/{job_id}",
    response_model=VisualJobResponseSchema,
    status_code=200
)
def get_image_job_status(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    get_project_or_404(db, project_id, workspace.id)

    try:
        record = get_or_create_job_record(project_id, job_id, db)
        return record
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post(
    "/projects/{project_id}/visual-jobs/{job_id}/approve",
    response_model=VisualJobResponseSchema,
    status_code=200
)
def approve_generated_image(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    get_project_or_404(db, project_id, workspace.id)

    record = get_or_create_job_record(project_id, job_id, db)
    if record.status != "needs_review":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a needs_review image can be approved.",
        )
    if not record.output_asset_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot approve a job that has no generated output asset."
        )

    # Verify output asset belongs to project
    asset = db.query(Asset).filter(Asset.id == record.output_asset_id).first()
    if not asset or asset.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Output asset not found or does not belong to this project."
        )

    record.status = "approved"
    db.commit()

    # Link output asset to page section's image_asset_id
    page = db.query(ProductPage).filter(ProductPage.project_id == project_id).first()
    if page:
        sec = db.query(PageSection).filter(
            PageSection.page_id == page.id,
            PageSection.id == record.section_id
        ).first()
        if sec:
            sec.image_asset_id = record.output_asset_id
            db.commit()

    sync_job_to_project_json(project_id, job_id, db)
    return record


@router.post(
    "/projects/{project_id}/visual-jobs/{job_id}/reject",
    response_model=VisualJobResponseSchema,
    status_code=200
)
def reject_generated_image(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    get_project_or_404(db, project_id, workspace.id)

    record = get_or_create_job_record(project_id, job_id, db)

    has_generated_output = bool(record.output_asset_id)
    record.status = "rejected" if has_generated_output else (
        "planned" if record.source_asset_ids else "needs_generation"
    )
    db.commit()

    # Restore original photo selection in corresponding page section's image_asset_id
    page = db.query(ProductPage).filter(ProductPage.project_id == project_id).first()
    if page:
        sec = db.query(PageSection).filter(
            PageSection.page_id == page.id,
            PageSection.id == record.section_id
        ).first()
        if sec:
            if record.source_asset_ids:
                sec.image_asset_id = record.source_asset_ids[0]
            else:
                sec.image_asset_id = None
            db.commit()

    sync_job_to_project_json(project_id, job_id, db)
    return record


@router.post(
    "/projects/{project_id}/visual-jobs/{job_id}/regenerate",
    response_model=VisualJobResponseSchema,
    status_code=200
)
def regenerate_image_for_job(
    project_id: str,
    job_id: str,
    req: RegenerateImageRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    get_project_or_404(db, project_id, workspace.id)

    record = get_or_create_job_record(project_id, job_id, db)

    # Update prompt if provided
    if req.prompt is not None:
        record.prompt = req.prompt

    # Reset job fields to trigger a new generation
    record.status = "needs_generation"
    record.output_asset_id = None
    record.error_code = None
    record.warnings = None
    db.commit()

    # Reset page section's image_asset_id since output is cleared
    page = db.query(ProductPage).filter(ProductPage.project_id == project_id).first()
    if page:
        sec = db.query(PageSection).filter(
            PageSection.page_id == page.id,
            PageSection.id == record.section_id
        ).first()
        if sec:
            sec.image_asset_id = None
            db.commit()

    sync_job_to_project_json(project_id, job_id, db)
    return record


class ImageReviewRequest(BaseModel):
    action: str  # approve, reject, regenerate, skip


@router.post("/projects/{project_id}/images/approve-cost")
def approve_image_generation_cost(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    project = get_project_or_404(db, project_id, workspace.id)

    from src.services.detail_page_orchestrator import DetailPageOrchestrator
    new_status = DetailPageOrchestrator.run_orchestration_pipeline(project_id, db, user_approved_cost=True)
    return {"status": "success", "project_status": new_status}


@router.post("/projects/{project_id}/images/review")
def review_generated_images(
    project_id: str,
    req: ImageReviewRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    project = get_project_or_404(db, project_id, workspace.id)

    jobs = db.query(ImageGenerationJobRecord).filter(
        ImageGenerationJobRecord.project_id == project_id
    ).all()

    if req.action == "regenerate":
        for job in jobs:
            if job.status == "needs_review":
                job.status = "generating"
                job.output_asset_id = None
                job.error_code = None
    elif req.action == "approve":
        for job in jobs:
            if job.status == "needs_review":
                job.status = "approved"
    elif req.action == "reject":
        for job in jobs:
            if job.status == "needs_review":
                job.status = "rejected"
    elif req.action == "skip":
        for job in jobs:
            if job.status == "needs_review":
                job.status = "skipped"
                job.output_asset_id = None

    db.commit()
    from src.services.image_generation_service import sync_job_to_project_json
    for job in jobs:
        sync_job_to_project_json(project_id, job.job_id, db)

    from src.services.detail_page_orchestrator import DetailPageOrchestrator
    new_status = DetailPageOrchestrator.run_orchestration_pipeline(project_id, db, user_approved_cost=True)
    return {"status": "success", "project_status": new_status}
