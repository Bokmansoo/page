"""Sprint 5 API for reviewable, storyboard-driven image redesign jobs."""

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.auth import get_current_user_and_workspace
from src.api.pages import get_project_or_404
from src.db.database import get_db
from src.db.models import ImageGenerationOutboxRecord, ScenePromptVersion
from src.services.storyboard_image_generation_service import (
    StoryboardImageGenerationError,
    approve_storyboard_job,
    attach_manual_storyboard_output,
    cancel_storyboard_job,
    list_storyboard_jobs,
    prepare_storyboard_jobs,
    reject_storyboard_job,
    restart_storyboard_job,
    run_storyboard_job_worker,
    storyboard_image_generation_is_available,
    start_storyboard_job,
    update_storyboard_job,
)
from src.services.visual_prompt_compiler_service import (
    VisualPromptCompileError,
    compile_project_scene_prompts,
    compile_scene_prompt,
    scene_prompt_payload,
)


router = APIRouter(tags=["Storyboard Image Generation"])


class StartStoryboardImageJobRequest(BaseModel):
    cost_approved: bool = False


class UpdateStoryboardImageJobRequest(BaseModel):
    instruction: Optional[str] = Field(default=None, max_length=600)
    # Preserve identity with an overall view plus a detail/control or usage view.
    source_asset_ids: Optional[list[str]] = Field(default=None, max_length=3)


class ApproveStoryboardImageJobRequest(BaseModel):
    identity_confirmed: bool = False


class AttachManualStoryboardOutputRequest(BaseModel):
    asset_id: str
    seller_attested: bool = False


class UpdateScenePromptRequest(BaseModel):
    seller_adjustment: str = Field(default="", max_length=600)


def _project(project_id: str, db: Session, auth_ctx: dict):
    return get_project_or_404(db, project_id, auth_ctx["workspace"].id)


def _raise(error: StoryboardImageGenerationError):
    raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/projects/{project_id}/scene-prompts")
def get_scene_prompts(
    project_id: str,
    include_stale: bool = False,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    project = _project(project_id, db, auth_ctx)
    query = db.query(ScenePromptVersion).filter(ScenePromptVersion.project_id == project.id)
    if not include_stale:
        query = query.filter(ScenePromptVersion.status == "active")
    rows = query.order_by(ScenePromptVersion.scene_id.asc(), ScenePromptVersion.version.desc()).all()
    return {"items": [scene_prompt_payload(row) for row in rows]}


@router.post("/projects/{project_id}/scene-prompts/compile")
def compile_scene_prompts(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    project = _project(project_id, db, auth_ctx)
    rows = compile_project_scene_prompts(project, db)
    return {"items": [scene_prompt_payload(row) for row in rows]}


@router.patch("/projects/{project_id}/scene-prompts/{scene_id}")
def revise_scene_prompt(
    project_id: str,
    scene_id: str,
    payload: UpdateScenePromptRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    project = _project(project_id, db, auth_ctx)
    card = next((item for item in (project.planning_draft or {}).get("cards") or [] if str(item.get("id")) == scene_id), None)
    if card is None:
        raise HTTPException(status_code=404, detail="스토리보드 장면을 찾을 수 없습니다.")
    try:
        row = compile_scene_prompt(project, card, db, seller_adjustment=payload.seller_adjustment.strip())
    except VisualPromptCompileError as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    db.commit()
    return scene_prompt_payload(row)


@router.get("/projects/{project_id}/storyboard/image-jobs")
def get_storyboard_image_jobs(project_id: str, db: Session = Depends(get_db), auth_ctx: dict = Depends(get_current_user_and_workspace)):
    return {
        "jobs": list_storyboard_jobs(_project(project_id, db, auth_ctx), db),
        "image_generation_available": storyboard_image_generation_is_available(),
    }


@router.post("/projects/{project_id}/storyboard/image-jobs")
def prepare_storyboard_image_jobs(project_id: str, db: Session = Depends(get_db), auth_ctx: dict = Depends(get_current_user_and_workspace)):
    try:
        return {
            "jobs": prepare_storyboard_jobs(_project(project_id, db, auth_ctx), db),
            "image_generation_available": storyboard_image_generation_is_available(),
        }
    except StoryboardImageGenerationError as error:
        _raise(error)


@router.patch("/projects/{project_id}/storyboard/image-jobs/{job_id}")
def update_storyboard_image_job(project_id: str, job_id: str, payload: UpdateStoryboardImageJobRequest, db: Session = Depends(get_db), auth_ctx: dict = Depends(get_current_user_and_workspace)):
    try:
        return update_storyboard_job(
            _project(project_id, db, auth_ctx), job_id, payload.instruction, db, payload.source_asset_ids
        )
    except StoryboardImageGenerationError as error:
        _raise(error)


@router.post("/projects/{project_id}/storyboard/image-jobs/{job_id}/start")
def start_storyboard_image_job(project_id: str, job_id: str, payload: StartStoryboardImageJobRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db), auth_ctx: dict = Depends(get_current_user_and_workspace)):
    try:
        result = start_storyboard_job(_project(project_id, db, auth_ctx), job_id, payload.cost_approved, db)
        if result.get("dispatch_required"):
            background_tasks.add_task(run_storyboard_job_worker, project_id, job_id)
        return result
    except StoryboardImageGenerationError as error:
        _raise(error)


@router.post("/projects/{project_id}/storyboard/image-jobs/{job_id}/approve")
def approve_storyboard_image_job(project_id: str, job_id: str, payload: ApproveStoryboardImageJobRequest, db: Session = Depends(get_db), auth_ctx: dict = Depends(get_current_user_and_workspace)):
    try:
        return approve_storyboard_job(_project(project_id, db, auth_ctx), job_id, db, payload.identity_confirmed)
    except StoryboardImageGenerationError as error:
        _raise(error)


@router.post("/projects/{project_id}/storyboard/image-jobs/{job_id}/manual-output")
def attach_manual_storyboard_image_output(project_id: str, job_id: str, payload: AttachManualStoryboardOutputRequest, db: Session = Depends(get_db), auth_ctx: dict = Depends(get_current_user_and_workspace)):
    """Use a seller-owned final image without requiring an image-provider API."""
    try:
        return attach_manual_storyboard_output(
            _project(project_id, db, auth_ctx), job_id, payload.asset_id, payload.seller_attested, db
        )
    except StoryboardImageGenerationError as error:
        _raise(error)


@router.post("/projects/{project_id}/storyboard/image-jobs/{job_id}/reject")
def reject_storyboard_image_job(project_id: str, job_id: str, db: Session = Depends(get_db), auth_ctx: dict = Depends(get_current_user_and_workspace)):
    try:
        return reject_storyboard_job(_project(project_id, db, auth_ctx), job_id, db)
    except StoryboardImageGenerationError as error:
        _raise(error)


@router.post("/projects/{project_id}/storyboard/image-jobs/{job_id}/cancel")
def cancel_storyboard_image_job(project_id: str, job_id: str, db: Session = Depends(get_db), auth_ctx: dict = Depends(get_current_user_and_workspace)):
    try:
        return cancel_storyboard_job(_project(project_id, db, auth_ctx), job_id, db)
    except StoryboardImageGenerationError as error:
        _raise(error)


@router.post("/projects/{project_id}/storyboard/image-jobs/{job_id}/regenerate")
def regenerate_storyboard_image_job(project_id: str, job_id: str, db: Session = Depends(get_db), auth_ctx: dict = Depends(get_current_user_and_workspace)):
    try:
        return restart_storyboard_job(_project(project_id, db, auth_ctx), job_id, db)
    except StoryboardImageGenerationError as error:
        _raise(error)


def _outbox_payload(item: ImageGenerationOutboxRecord) -> dict:
    return {
        "id": item.id,
        "project_id": item.project_id,
        "run_id": item.run_id,
        "job_id": item.job_id,
        "idempotency_key": item.idempotency_key,
        "provider_mode": item.provider_mode,
        "status": item.status,
        "lease_owner": item.lease_owner,
        "lease_expires_at": item.lease_expires_at,
        "delivery_attempts": item.delivery_attempts,
        "provider_dispatch_count": item.provider_dispatch_count,
        "completion_resume_count": item.completion_resume_count,
        "last_error_code": item.last_error_code,
        "last_error_message": item.last_error_message,
    }


@router.get("/image-worker/outbox")
def get_image_worker_outbox(
    status: str | None = None,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    query = db.query(ImageGenerationOutboxRecord).filter(
        ImageGenerationOutboxRecord.workspace_id == auth_ctx["workspace"].id
    )
    if status:
        query = query.filter(ImageGenerationOutboxRecord.status == status)
    return {
        "items": [
            _outbox_payload(item)
            for item in query.order_by(ImageGenerationOutboxRecord.created_at.desc()).all()
        ]
    }


@router.post("/image-worker/recovery-sweep")
def recover_image_worker_leases(
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    from src.services.image_generation_worker import recover_expired_image_work

    return recover_expired_image_work(db, workspace_id=auth_ctx["workspace"].id)


@router.post("/image-worker/outbox/{delivery_id}/retry")
def retry_image_worker_dead_letter(
    delivery_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    from src.services.image_generation_worker import retry_dead_letter

    delivery = db.query(ImageGenerationOutboxRecord).filter(
        ImageGenerationOutboxRecord.id == delivery_id,
        ImageGenerationOutboxRecord.workspace_id == auth_ctx["workspace"].id,
    ).first()
    if delivery is None:
        raise HTTPException(status_code=404, detail="이미지 worker 작업을 찾을 수 없습니다.")
    try:
        return _outbox_payload(retry_dead_letter(delivery.id, db))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
