from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.auth import get_current_user_and_workspace, require_roles
from src.db.database import get_db
from src.db.models import AgentRun, Asset, ProductCreativeBriefVersion, ProductProject
from src.services.creative_brief_llm_service import CreativeBriefLLMError
from src.services.creative_brief_service import (
    CreativeBriefInputError,
    compile_creative_brief,
    create_creative_direction,
    create_reference_input,
    create_review_input,
    normalize_interaction_mode,
    parse_review_bytes,
    project_intelligence,
    review_text_from_asset,
)

router = APIRouter(tags=["creative-briefs"])


def _project(db: Session, project_id: str, workspace_id: str) -> ProductProject:
    row = db.query(ProductProject).filter_by(id=project_id, workspace_id=workspace_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return row


def _run(db: Session, run_id: str, workspace_id: str) -> AgentRun:
    row = db.query(AgentRun).filter_by(id=run_id, workspace_id=workspace_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Agent run not found.")
    return row


class ReferenceRequest(BaseModel):
    input_kind: Literal["url", "image", "pdf", "text"]
    text: str = ""
    source_url: str = ""
    asset_id: str | None = None
    rights_status: Literal["unverified", "verified", "seller_owned", "licensed"] = "unverified"
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class CreativeDirectionRequest(BaseModel):
    desired_mood: list[str] = Field(default_factory=list, max_length=20)
    target_audience: str = Field(default="", max_length=2000)
    emphasis: list[str] = Field(default_factory=list, max_length=20)
    forbidden_scenes: list[str] = Field(default_factory=list, max_length=20)


class InteractionModeRequest(BaseModel):
    interaction_mode: Literal["quick", "expert"]


@router.get("/projects/{project_id}/creative-intelligence")
def get_creative_intelligence(project_id: str, run_id: str | None = None, db: Session = Depends(get_db),
                              auth_ctx: dict = Depends(get_current_user_and_workspace)):
    project = _project(db, project_id, auth_ctx["workspace"].id)
    data = project_intelligence(db, project.id, run_id=run_id)
    data["interaction_mode"] = normalize_interaction_mode(project.planning_mode)
    return data


@router.post("/projects/{project_id}/review-inputs")
async def add_review_input(
    project_id: str,
    text: str = Form(default=""),
    source_label: str = Form(default=""),
    consent_status: str = Form(default="unconfirmed"),
    rights_status: str = Form(default="unverified"),
    source_asset_id: str = Form(default=""),
    file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(require_roles(["owner", "admin", "member"])),
):
    project = _project(db, project_id, auth_ctx["workspace"].id)
    input_format = "paste"
    body = text
    selected_asset: Asset | None = None
    if file is not None and source_asset_id:
        raise HTTPException(status_code=400, detail={
            "code": "REVIEW_SOURCE_CONFLICT",
            "message": "리뷰 파일과 기존 수집 자료를 동시에 선택할 수 없습니다.",
            "remedy": "둘 중 하나만 선택한 뒤 다시 저장해 주세요.",
        })
    if source_asset_id:
        selected_asset = db.query(Asset).filter(
            Asset.id == source_asset_id,
            Asset.project_id == project.id,
            Asset.usage_status.notin_(["blocked", "ai_generated"]),
        ).first()
        if selected_asset is None:
            raise HTTPException(status_code=400, detail={
                "code": "REVIEW_ASSET_NOT_ALLOWED",
                "message": "선택한 자료를 리뷰 분석에 사용할 수 없습니다.",
                "remedy": "이 프로젝트의 허용된 수집 자료를 다시 선택해 주세요.",
            })
        try:
            body = review_text_from_asset(selected_asset)
        except CreativeBriefInputError as exc:
            raise HTTPException(status_code=400, detail=exc.as_detail()) from exc
        input_format = "collected_asset"
    if file is not None:
        try:
            input_format, body = parse_review_bytes(file.filename or "reviews.txt", await file.read())
        except CreativeBriefInputError as exc:
            raise HTTPException(status_code=400, detail=exc.as_detail()) from exc
        except OSError as exc:
            raise HTTPException(status_code=400, detail={
                "code": "REVIEW_FILE_READ_FAILED",
                "message": "리뷰 파일을 읽지 못했습니다.",
                "remedy": "파일 권한과 형식을 확인한 뒤 다시 업로드해 주세요.",
            }) from exc
    try:
        row = create_review_input(
            db, project=project, user_id=auth_ctx["user"].id, input_format=input_format,
            text=body,
            source_label=source_label or (file.filename if file else (selected_asset.filename if selected_asset else "")),
            consent_status=consent_status, rights_status=rights_status,
            source_asset_id=selected_asset.id if selected_asset else None,
            source_metadata={
                "source_asset_id": selected_asset.id,
                "source_content_hash": selected_asset.content_hash,
                "source_type": selected_asset.source_type,
            } if selected_asset else {},
        )
    except CreativeBriefInputError as exc:
        raise HTTPException(status_code=400, detail=exc.as_detail()) from exc
    return {"id": row.id, "version": row.version, "content_hash": row.content_hash,
            "fact_promotion_status": "blocked", "deduplicated": bool(getattr(row, "_deduplicated", False))}


@router.post("/projects/{project_id}/reference-inputs")
def add_reference_input(project_id: str, payload: ReferenceRequest, db: Session = Depends(get_db),
                        auth_ctx: dict = Depends(require_roles(["owner", "admin", "member"]))):
    project = _project(db, project_id, auth_ctx["workspace"].id)
    try:
        row = create_reference_input(
            db, project=project, user_id=auth_ctx["user"].id, input_kind=payload.input_kind,
            text=payload.text, source_url=payload.source_url, asset_id=payload.asset_id,
            rights_status=payload.rights_status, source_metadata=payload.source_metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": row.id, "version": row.version, "content_hash": row.content_hash,
            "rights_status": row.rights_status, "usage_scope": row.usage_scope}


@router.post("/projects/{project_id}/creative-direction")
def add_creative_direction(project_id: str, payload: CreativeDirectionRequest,
                           db: Session = Depends(get_db),
                           auth_ctx: dict = Depends(require_roles(["owner", "admin", "member"]))):
    project = _project(db, project_id, auth_ctx["workspace"].id)
    row = create_creative_direction(
        db, project=project, user_id=auth_ctx["user"].id,
        desired_mood=payload.desired_mood, target_audience=payload.target_audience,
        emphasis=payload.emphasis, forbidden_scenes=payload.forbidden_scenes,
    )
    return {"id": row.id, "version": row.version, "content_hash": row.content_hash}


@router.patch("/agent-runs/{run_id}/interaction-mode")
def set_interaction_mode(run_id: str, payload: InteractionModeRequest, db: Session = Depends(get_db),
                         auth_ctx: dict = Depends(require_roles(["owner", "admin", "member"]))):
    run = _run(db, run_id, auth_ctx["workspace"].id)
    mode = normalize_interaction_mode(payload.interaction_mode)
    run.project.planning_mode = mode
    snapshot = dict(run.input_snapshot or {})
    snapshot["interaction_mode"] = mode
    run.input_snapshot = snapshot
    db.commit()
    return {"run_id": run.id, "interaction_mode": mode, "artifacts_preserved": True}


@router.post("/agent-runs/{run_id}/creative-brief/compile")
def compile_brief(run_id: str, db: Session = Depends(get_db),
                  auth_ctx: dict = Depends(require_roles(["owner", "admin", "member"]))):
    run = _run(db, run_id, auth_ctx["workspace"].id)
    try:
        row = compile_creative_brief(db, run)
    except CreativeBriefLLMError as exc:
        raise HTTPException(status_code=422, detail=exc.as_detail()) from exc
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": row.id, "version": row.version, "input_hash": row.input_hash,
            "output_hash": row.output_hash, "brief": row.brief_json}


@router.get("/agent-runs/{run_id}/creative-brief")
def get_brief(run_id: str, db: Session = Depends(get_db),
              auth_ctx: dict = Depends(get_current_user_and_workspace)):
    run = _run(db, run_id, auth_ctx["workspace"].id)
    row = db.query(ProductCreativeBriefVersion).filter_by(run_id=run.id).order_by(
        ProductCreativeBriefVersion.created_at.desc()).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Creative brief has not been compiled.")
    return {"id": row.id, "version": row.version, "input_hash": row.input_hash,
            "output_hash": row.output_hash, "brief": row.brief_json}
