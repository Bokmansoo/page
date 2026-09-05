"""Seller-safe LG-16 common-video studio API."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from src.api.auth import get_current_user_and_workspace
from src.db.database import get_db
from src.db.models import (
    AgentRun,
    Asset,
    ProductProject,
    VideoPlatformMetadataVersion,
    VideoProjectVersion,
    VideoTextVersion,
)
from src.services.langgraph_run_service import AgentRunEventJournal, GraphRunNotFound
from src.services.video_platform_metadata_service import (
    VideoPlatformMetadataContractError,
    create_video_platform_metadata_version,
    public_video_platform_metadata_projection,
)
from src.services.video_project_version_service import (
    VideoProjectContractError,
    public_video_project_projection,
)
from src.services.video_scene_generation_service import (
    VideoSceneGenerationError,
    collect_video_scene_results,
    dispatch_video_scene_jobs,
    prepare_video_scene_jobs,
)
from src.services.video_storyboard_service import (
    VideoStoryboardContractError,
    create_video_storyboard_version,
    public_video_storyboard_projection,
)
from src.services.video_text_service import (
    VideoTextContractError,
    create_video_text_version,
    public_video_text_projection,
)


router = APIRouter(prefix="/projects/{project_id}/video", tags=["video"])
_EDIT_ROLES = {"owner", "admin", "member", "editor"}
_PLATFORMS = {"reels", "tiktok", "youtube_shorts"}


class VideoActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    action: Literal["reorder", "regenerate", "text_edit", "metadata_edit"]
    parent_video_project_ref: dict[str, Any]
    scene_id: str | None = None
    ordered_scene_ids: list[str] = Field(default_factory=list)
    text_role: Literal["scene_copy", "overlay_text", "caption_text"] = "scene_copy"
    placement_role: Literal["headline", "body", "cta", "caption"] = "body"
    body_text: str | None = Field(default=None, max_length=2000)
    platform: Literal["reels", "tiktok", "youtube_shorts"] | None = None
    title: str | None = Field(default=None, max_length=500)
    caption: str | None = Field(default=None, max_length=2000)
    description: str | None = Field(default=None, max_length=5000)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    cta: str | None = Field(default=None, max_length=500)
    parent_metadata_version_id: str | None = None


def _project(db: Session, project_id: str, workspace_id: str) -> ProductProject:
    project = db.query(ProductProject).filter_by(id=project_id, workspace_id=workspace_id).one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Product project not found")
    return project


def _run(db: Session, project_id: str, workspace_id: str, run_id: str | None = None) -> AgentRun | None:
    query = db.query(AgentRun).filter_by(
        project_id=project_id, workspace_id=workspace_id, mode="lg16_video_project",
    )
    run = query.filter_by(id=run_id).one_or_none() if run_id else query.order_by(AgentRun.updated_at.desc(), AgentRun.created_at.desc()).first()
    if run is not None:
        # A worker/assembly may have committed the projection through another
        # session; the studio must read the persisted authority, not an ORM
        # identity-map snapshot left by a preceding command.
        db.refresh(run)
    return run


def _video(db: Session, project_id: str, workspace_id: str) -> VideoProjectVersion | None:
    return (
        db.query(VideoProjectVersion)
        .filter_by(project_id=project_id, workspace_id=workspace_id)
        .order_by(VideoProjectVersion.version.desc())
        .first()
    )


def _safe_status(run: AgentRun, *, assembly: dict[str, Any], generation: dict[str, Any], ready: bool = False) -> dict[str, Any]:
    if run.status == "awaiting_review":
        label = "확인이 필요합니다"
    elif ready or assembly.get("final_asset_ref"):
        label = "게시 준비 완료"
    elif generation.get("pending_count"):
        label = "장면 생성 중"
    else:
        label = "영상 준비 중"
    quality = dict((run.outputs_json or {}).get("langgraph_quality") or {})
    verdict = str(quality.get("verdict") or "PENDING").upper()
    state = "review" if run.status == "awaiting_review" else "ready" if ready or assembly.get("final_asset_ref") else "processing"
    return {"status": state, "label": label, "quality": "통과" if verdict == "PASS" else "검토 필요"}


def _safe_scene(scene: dict[str, Any], job: dict[str, Any] | None) -> dict[str, Any]:
    status_value = str((job or {}).get("status") or "planned")
    if status_value in {"completed", "needs_review", "approved"}:
        seller_status = "완료"
    elif status_value in {"failed", "blocked"}:
        seller_status = "검토 필요"
    else:
        seller_status = "준비 중"
    return {
        "scene_id": str(scene.get("scene_id") or ""),
        "order": int(scene.get("order") or 0),
        "role": str(scene.get("role") or "scene"),
        "title": str(scene.get("logical_target") or scene.get("role") or "장면"),
        "status": seller_status,
        "generation_status": seller_status,
        "text_ready": bool(scene.get("copy_ref") or scene.get("caption_ref")),
    }


def _safe_text(row: VideoTextVersion) -> dict[str, Any]:
    projection = public_video_text_projection(row)
    return {key: projection[key] for key in ("id", "version", "scene_id", "text_role", "placement_role", "visibility_status", "text", "validation_status")}


def _safe_metadata(row: VideoPlatformMetadataVersion) -> dict[str, Any]:
    projection = public_video_platform_metadata_projection(row)
    return {key: projection[key] for key in ("id", "version", "platform", "title", "caption", "description", "hashtags", "cta", "validation_status")}


def _asset_path(asset: Asset) -> Path | None:
    raw = Path(str(asset.file_path or ""))
    candidates = [raw]
    if not raw.is_absolute():
        candidates.append(Path(__file__).resolve().parents[2] / raw)
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _projection(db: Session, run: AgentRun, video: VideoProjectVersion) -> dict[str, Any]:
    project_projection = public_video_project_projection(db, video)
    storyboard = public_video_storyboard_projection(db, video)
    try:
        generation = collect_video_scene_results(run_id=run.id, project_id=run.project_id, db=db)
    except VideoSceneGenerationError:
        generation = {"scene_count": storyboard["scene_count"], "completed_count": 0, "pending_count": storyboard["scene_count"], "failed_count": 0, "jobs": []}
    jobs = {str(item.get("scene_id")): item for item in generation.get("jobs") or []}
    scenes = [_safe_scene(scene, jobs.get(str(scene.get("scene_id")))) for scene in storyboard["scenes"]]

    assembly = dict((run.outputs_json or {}).get("langgraph_video_assembly") or {})
    manifest = dict(project_projection.get("video_manifest") or {})
    authoritative_ref = dict(manifest.get("final_output_ref") or {})
    final_ref = authoritative_ref
    final_asset = None
    if final_ref.get("id"):
        query = db.query(Asset).filter_by(id=final_ref["id"], project_id=run.project_id, asset_role="video_final", mime_type="video/mp4")
        if final_ref.get("hash"):
            query = query.filter(Asset.content_hash == final_ref["hash"])
        final_asset = query.one_or_none()
    assembly_ref = dict(assembly.get("final_asset_ref") or {})
    current_assembly = assembly if (
        authoritative_ref.get("id") == assembly_ref.get("id")
        and authoritative_ref.get("hash") == assembly_ref.get("hash")
    ) else {}
    text_refs = list((video.video_manifest_json or {}).get("text_layer_refs") or [])
    texts = []
    for ref in text_refs:
        if not isinstance(ref, dict) or not ref.get("id"):
            continue
        row = db.query(VideoTextVersion).filter_by(id=ref["id"], project_id=run.project_id).one_or_none()
        if row is not None and str(row.body_hash) == str(ref.get("hash")):
            texts.append(_safe_text(row))
    metadata_rows = db.query(VideoPlatformMetadataVersion).filter_by(project_id=run.project_id, video_project_version_id=video.id).order_by(VideoPlatformMetadataVersion.platform, VideoPlatformMetadataVersion.version.desc()).all()
    latest_metadata: dict[str, dict[str, Any]] = {}
    for row in metadata_rows:
        latest_metadata.setdefault(row.platform, _safe_metadata(row))
    final_path = _asset_path(final_asset) if final_asset is not None else None
    ready = bool(final_path and final_path.stat().st_size > 0 and str(final_asset.content_hash) == str(authoritative_ref.get("hash")))
    audio_ref = dict(manifest.get("audio_ref") or {})
    thumbnail_ref = dict(manifest.get("thumbnail_ref") or {})
    return {
        "video": {
            "id": str(video.id), "version": int(video.version),
            "publishing_targets": list(video.publishing_targets_json or []),
            "scene_count": int(storyboard["scene_count"]), "scenes": scenes,
            "progress": {"completed_count": int(generation.get("completed_count") or 0), "total_count": int(storyboard["scene_count"]), "percent": round((int(generation.get("completed_count") or 0) / max(1, int(storyboard["scene_count"]))) * 100)},
            "current_stage": "영상 결과 확인" if ready else "장면 생성",
            "status": _safe_status(run, assembly=current_assembly, generation=generation, ready=ready),
            "assembly": {"ready": ready, "duration_seconds": current_assembly.get("duration_seconds"), "quality": "통과" if current_assembly.get("quality_verdict") == "PASS" else "검토 필요"},
            "final_output": {"ready": ready, "media_type": "video/mp4" if authoritative_ref else None, "version": int(video.version) if authoritative_ref else None},
            "audio": {"mode": "silent" if audio_ref.get("id") == "audio:silent" else "unspecified"},
            "thumbnail": {"ready": bool(thumbnail_ref.get("id")), "media_type": "image/png" if thumbnail_ref else None},
            "download_available": ready,
            "texts": texts,
            "metadata": list(latest_metadata.values()),
            "actions": ["regenerate", "text_edit", "metadata_edit"] + (["download"] if ready else []),
        },
        "run_id": str(run.id),
    }


def _require_parent(db: Session, payload: VideoActionRequest, video: VideoProjectVersion, project_id: str, workspace_id: str) -> None:
    supplied = payload.parent_video_project_ref or {}
    if str(supplied.get("id") or "") != str(video.id) or int(supplied.get("version") or 0) != int(video.version):
        raise HTTPException(status_code=409, detail={"code": "video_stale", "message": "영상이 변경되었습니다. 최신 상태를 다시 불러와 주세요."})
    if supplied.get("hash") and str(supplied.get("hash")) != str(video.canonical_hash):
        raise HTTPException(status_code=409, detail={"code": "video_stale", "message": "영상이 변경되었습니다. 최신 상태를 다시 불러와 주세요."})


@router.get("")
def get_video(project_id: str, db: Session = Depends(get_db), auth_ctx: dict = Depends(get_current_user_and_workspace)):
    workspace_id = auth_ctx["workspace"].id
    _project(db, project_id, workspace_id)
    run = _run(db, project_id, workspace_id)
    video = _video(db, project_id, workspace_id)
    if run is None or video is None:
        raise HTTPException(status_code=404, detail="Video project not found")
    try:
        return _projection(db, run, video)
    except (VideoProjectContractError, VideoStoryboardContractError) as exc:
        raise HTTPException(status_code=409, detail={"code": "video_unavailable", "message": "영상 상태를 확인할 수 없습니다. 최신 상태를 다시 불러와 주세요."}) from exc


@router.post("/actions")
def video_action(project_id: str, payload: VideoActionRequest, db: Session = Depends(get_db), auth_ctx: dict = Depends(get_current_user_and_workspace)):
    workspace_id = auth_ctx["workspace"].id
    _project(db, project_id, workspace_id)
    if (auth_ctx.get("role") or "owner") not in _EDIT_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: insufficient workspace permission")
    run = _run(db, project_id, workspace_id, payload.run_id)
    video = _video(db, project_id, workspace_id)
    if run is None or video is None:
        raise HTTPException(status_code=404, detail="Video project not found")
    _require_parent(db, payload, video, project_id, workspace_id)
    try:
        result: dict[str, Any]
        if payload.action == "reorder":
            storyboard = dict((video.video_manifest_json or {}).get("storyboard") or {})
            full_scenes = list(storyboard.get("scenes") or [])
            by_id = {str(item["scene_id"]): item for item in full_scenes if isinstance(item, dict)}
            if set(payload.ordered_scene_ids) != set(by_id) or len(payload.ordered_scene_ids) != len(by_id):
                raise VideoStoryboardContractError("Scene order is invalid.")
            scenes = [deepcopy(by_id[scene_id]) | {"order": index} for index, scene_id in enumerate(payload.ordered_scene_ids, 1)]
            successor = create_video_storyboard_version(db, video_project=video, scenes=scenes, creator_run_id=run.id, created_by=auth_ctx["user"].id)
            storyboard = dict((successor.video_manifest_json or {}).get("storyboard") or {})
            successor_ref = {"id": str(successor.id), "version": int(successor.version), "hash": str(successor.canonical_hash)}
            storyboard_ref = {"id": str(storyboard.get("storyboard_id") or ""), "version": 1, "hash": str(storyboard.get("canonical_hash") or "")}
            AgentRunEventJournal.append(
                run,
                db,
                event_type="video_storyboard_planned",
                payload={
                    "stage": "video_storyboard_reorder",
                    "status": str(run.status or "completed"),
                    "node_status": "completed",
                    "input_mode": "",
                    "source_fidelity": "ready",
                    "references": {"video_project": successor_ref, "storyboard": storyboard_ref},
                    "metrics": {"unknown_fact_count": 0, "prohibited_inference_count": 0, "clarification_count": 0},
                    "lifecycle": {"transition": "completed", "checkpoint_id": ""},
                    "video": {
                        "video_project_ref": successor_ref,
                        "storyboard_ref": storyboard_ref,
                        "scene_count": int(storyboard.get("scene_count") or len(scenes)),
                        "status": "planned",
                        "execution_mode": "deterministic_fake",
                    },
                },
                thread_id=run.graph_thread_id or run.id,
                workspace_id=run.workspace_id,
                project_id=run.project_id,
            )
            outputs = dict(run.outputs_json or {})
            video_projection = dict(outputs.get("langgraph_video") or {})
            video_projection.update({"video_project_ref": successor_ref, "storyboard_ref": storyboard_ref})
            outputs["langgraph_video"] = video_projection
            run.outputs_json = outputs
            db.commit()
            result = {"replayed": False, "successor": successor}
        elif payload.action == "regenerate":
            if not payload.scene_id:
                raise VideoSceneGenerationError("VIDEO_SCENE_SCOPE_INVALID")
            generation = prepare_video_scene_jobs(run_id=run.id, project_id=project_id, db=db, regenerate_scene_ids=[payload.scene_id])
            dispatch_video_scene_jobs(run_id=run.id, project_id=project_id, db=db)
            result = {"replayed": False, "generation": generation}
        elif payload.action == "text_edit":
            if not payload.scene_id or payload.body_text is None:
                raise VideoTextContractError("Text scene and body are required.")
            storyboard = public_video_storyboard_projection(db, video)
            scene = next((item for item in storyboard["scenes"] if str(item["scene_id"]) == payload.scene_id), None)
            if scene is None:
                raise VideoTextContractError("Text scene is missing or stale.")
            result = create_video_text_version(db, workspace_id=workspace_id, project_id=project_id, parent_video_project_version_id=video.id, scene_id=payload.scene_id, text_role=payload.text_role, placement_role=payload.placement_role, body_text=payload.body_text, author_id=auth_ctx["user"].id, fact_refs=scene["fact_refs"], provenance_refs=scene["provenance_refs"])
            db.commit()
        else:
            if payload.platform is None:
                raise VideoPlatformMetadataContractError("Platform is required.")
            manifest = dict(video.video_manifest_json or {})
            final_ref = dict(manifest.get("final_output_ref") or {})
            storyboard = public_video_storyboard_projection(db, video)
            fact_refs = list(storyboard["scenes"][0]["fact_refs"])
            provenance_refs = list(storyboard["scenes"][0]["provenance_refs"])
            result = create_video_platform_metadata_version(db, workspace_id=workspace_id, project_id=project_id, video_project_version_id=video.id, final_asset_reference=final_ref, platform=payload.platform, author_id=auth_ctx["user"].id, fact_refs=fact_refs, provenance_refs=provenance_refs, text_refs=list((video.video_manifest_json or {}).get("text_layer_refs") or []), title=payload.title, caption=payload.caption, description=payload.description, hashtags=payload.hashtags, cta=payload.cta, parent_metadata_version_id=payload.parent_metadata_version_id)
            db.commit()
        current = _video(db, project_id, workspace_id) or video
        return {"run_id": str(run.id), "action": payload.action, "replayed": bool(result.get("replayed")), **_projection(db, run, current)}
    except (VideoProjectContractError, VideoStoryboardContractError, VideoSceneGenerationError, VideoTextContractError, VideoPlatformMetadataContractError, GraphRunNotFound) as exc:
        db.rollback()
        internal_message = str(exc)
        code = "video_stale" if "stale" in internal_message.lower() else "video_action_rejected"
        message = "영상이 변경되었습니다. 최신 상태를 다시 불러와 주세요." if code == "video_stale" else "영상 작업을 적용하지 못했습니다. 입력을 확인한 뒤 다시 시도해 주세요."
        raise HTTPException(status_code=409, detail={"code": code, "message": message}) from exc


@router.get("/download")
def download_video(project_id: str, db: Session = Depends(get_db), auth_ctx: dict = Depends(get_current_user_and_workspace)):
    workspace_id = auth_ctx["workspace"].id
    _project(db, project_id, workspace_id)
    run = _run(db, project_id, workspace_id)
    video = _video(db, project_id, workspace_id)
    if run is None or video is None:
        raise HTTPException(status_code=404, detail="Video project not found")
    final_ref = dict((video.video_manifest_json or {}).get("final_output_ref") or {})
    asset_query = db.query(Asset).filter_by(id=final_ref.get("id"), project_id=project_id, asset_role="video_final", mime_type="video/mp4")
    if final_ref.get("hash"):
        asset_query = asset_query.filter(Asset.content_hash == final_ref["hash"])
    asset = asset_query.one_or_none() if final_ref.get("id") else None
    path = _asset_path(asset) if asset is not None else None
    if asset is None or path is None or path.stat().st_size <= 0 or str(asset.content_hash) != str(final_ref.get("hash")):
        raise HTTPException(status_code=409, detail="Final video is not ready")
    return FileResponse(path, media_type="video/mp4", filename=f"video-final-v{video.version}.mp4")
