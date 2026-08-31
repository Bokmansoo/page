"""Seller-safe LG-15 Social Creative Kit API."""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from src.api.auth import get_current_user_and_workspace
from src.config import settings
from src.db.database import get_db
from src.db.models import AgentRun, Asset, ProductProject, SocialKitVersion
from src.services.langgraph_run_service import GraphRunNotFound, LangGraphRunService
from src.services.social_kit_version_service import (
    SocialKitContractError,
    apply_social_card_action,
    evaluate_social_platform_quality,
    public_social_kit_projection,
)


router = APIRouter(prefix="/projects/{project_id}/social-kit", tags=["social-kit"])


class SocialKitStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_master_reference: dict[str, Any]
    target_channel: str = "smartstore"
    target_format: str = "card"
    channel_contract_reference: dict[str, Any]
    logical_targets: list[str] = Field(default_factory=lambda: ["hero", "benefit", "feature", "usage", "cta"])
    template_version: str = "lg15-fake-template-v1"
    evaluator_version: str = "lg15-fake-evaluator-v1"
    parent_version_id: str | None = None
    execution_mode: str = "deterministic_fake"


class SocialKitActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    action: Literal["reorder", "delete", "regenerate", "request_alternative", "select_alternative", "edit_copy"]
    parent_social_kit_ref: dict[str, Any]
    card_id: str | None = None
    ordered_card_ids: list[str] = Field(default_factory=list)
    variant_key: str | None = None
    variant_ref: dict[str, Any] | None = None
    copy_reference: dict[str, Any] | None = None
    proposed_text: str | None = Field(default=None, max_length=2000)


def _project(db: Session, project_id: str, workspace_id: str) -> ProductProject:
    project = db.query(ProductProject).filter_by(id=project_id, workspace_id=workspace_id).one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Product project not found")
    return project


def _run_for_kit(db: Session, project_id: str, workspace_id: str, run_id: str | None = None) -> AgentRun | None:
    query = db.query(AgentRun).filter_by(workspace_id=workspace_id, project_id=project_id, mode="lg15_social_kit")
    if run_id:
        return query.filter_by(id=run_id).one_or_none()
    return query.order_by(AgentRun.updated_at.desc(), AgentRun.created_at.desc()).first()


def _kit_for_run(db: Session, run: AgentRun | None, project_id: str, workspace_id: str) -> SocialKitVersion | None:
    latest = db.query(SocialKitVersion).filter_by(
        project_id=project_id, workspace_id=workspace_id,
    ).order_by(SocialKitVersion.version.desc()).first()
    if latest is not None:
        return latest
    if run is not None:
        ref = dict((dict(run.outputs_json or {}).get("langgraph_social") or {}).get("social_kit_ref") or {})
        if ref.get("id"):
            kit = db.query(SocialKitVersion).filter_by(
                id=ref["id"], project_id=project_id, workspace_id=workspace_id,
            ).one_or_none()
            if kit is not None:
                return kit
    return None


def _response(db: Session, kit: SocialKitVersion, run: AgentRun | None) -> dict[str, Any]:
    return {"run_id": str(run.id) if run is not None else None, "kit": public_social_kit_projection(db, kit, run)}


@router.get("")
def get_social_kit(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    _project(db, project_id, auth_ctx["workspace"].id)
    run = _run_for_kit(db, project_id, auth_ctx["workspace"].id)
    kit = _kit_for_run(db, run, project_id, auth_ctx["workspace"].id)
    if kit is None:
        raise HTTPException(status_code=404, detail="Social Creative Kit not found")
    try:
        return _response(db, kit, run)
    except SocialKitContractError as exc:
        raise HTTPException(status_code=409, detail={"code": "social_kit_unavailable", "message": str(exc)}) from exc


@router.post("", status_code=status.HTTP_201_CREATED)
def start_social_kit(
    project_id: str,
    payload: SocialKitStartRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    _project(db, project_id, auth_ctx["workspace"].id)
    if (auth_ctx.get("role") or "owner") not in {"owner", "admin", "member", "editor"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: insufficient workspace permission")
    try:
        run = LangGraphRunService.start_social_kit(
            project_id=project_id,
            workspace_id=auth_ctx["workspace"].id,
            actor_id=auth_ctx["user"].id,
            request=payload.model_dump(),
            db=db,
        )
        kit = _kit_for_run(db, run, project_id, auth_ctx["workspace"].id)
        if kit is None:
            raise SocialKitContractError("Social Creative Kit was not persisted.")
        return _response(db, kit, run)
    except (ValueError, GraphRunNotFound) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/actions")
def social_kit_action(
    project_id: str,
    payload: SocialKitActionRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    _project(db, project_id, auth_ctx["workspace"].id)
    role = auth_ctx.get("role") or "owner"
    if role not in {"owner", "admin", "member", "editor"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: insufficient workspace permission")
    run = _run_for_kit(db, project_id, auth_ctx["workspace"].id, payload.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Social Creative Kit run not found")
    parent_id = str(payload.parent_social_kit_ref.get("id") or "")
    parent = db.query(SocialKitVersion).filter_by(
        id=parent_id, project_id=project_id, workspace_id=auth_ctx["workspace"].id,
    ).one_or_none()
    if parent is None:
        raise HTTPException(status_code=404, detail="Social Creative Kit version not found")
    request = payload.model_dump(exclude={"run_id"})
    request["parent_social_kit_ref"] = {
        "id": str(parent.id), "version": int(parent.version), "hash": str(parent.canonical_hash),
    }
    try:
        result = apply_social_card_action(db, run=run, request=request)
        kit = result["successor"]
        return {
            "run_id": str(run.id),
            "replayed": bool(result.get("replayed")),
            "action": result["action"],
            "kit": public_social_kit_projection(db, kit, run),
        }
    except SocialKitContractError as exc:
        message = str(exc)
        code = "social_kit_action_rejected" if "stale" not in message.lower() else "social_kit_stale"
        raise HTTPException(status_code=409, detail={"code": code, "message": message}) from exc


def _render_asset(db: Session, project_id: str, workspace_id: str, asset_id: str) -> Asset:
    asset = (
        db.query(Asset)
        .join(ProductProject, ProductProject.id == Asset.project_id)
        .filter(Asset.id == asset_id, Asset.project_id == project_id, ProductProject.workspace_id == workspace_id)
        .one_or_none()
    )
    if asset is None or not asset.file_path or not os.path.isfile(asset.file_path):
        raise HTTPException(status_code=404, detail="Social card preview is not available")
    if not str(asset.mime_type or "").startswith("image/"):
        raise HTTPException(status_code=409, detail="Social card preview is not an image")
    return asset


@router.get("/export/{output_format}")
def export_social_kit(
    project_id: str,
    output_format: Literal["png", "jpg", "zip"],
    card_id: str | None = None,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    _project(db, project_id, auth_ctx["workspace"].id)
    run = _run_for_kit(db, project_id, auth_ctx["workspace"].id)
    kit = _kit_for_run(db, run, project_id, auth_ctx["workspace"].id)
    if kit is None:
        raise HTTPException(status_code=404, detail="Social Creative Kit not found")
    projection = public_social_kit_projection(db, kit, run)
    cards = list(projection.get("cards") or [])
    if not cards or any(card.get("status") != "rendered" for card in cards):
        raise HTTPException(status_code=409, detail="Social cards must finish rendering before export")
    if kit.target_channel == "instagram" and kit.target_format == "feed_portrait":
        platform_quality = evaluate_social_platform_quality(
            db, kit, dict((dict((run.outputs_json or {}).get("langgraph_social") or {}).get("render") or {})),
        )
        if platform_quality["verdict"] != "PASS":
            raise HTTPException(status_code=409, detail="Instagram publishing profile validation failed")
    if card_id:
        cards = [card for card in cards if card.get("card_id") == card_id]
        if not cards:
            raise HTTPException(status_code=404, detail="Social card not found")
    root = Path(settings.UPLOAD_DIR) / "social-exports" / str(kit.id)
    root.mkdir(parents=True, exist_ok=True)
    if output_format in {"png", "jpg"}:
        from PIL import Image

        card = cards[0]
        asset_ref = dict(card["preview_asset_ref"])
        source = _render_asset(db, project_id, auth_ctx["workspace"].id, asset_ref["id"])
        filename = (
            f"instagram-feed-portrait-{int(card['order']):02d}.{output_format}"
            if kit.target_channel == "instagram" and kit.target_format == "feed_portrait"
            else f"social-{kit.id}-v{kit.version}-{card['card_id']}-{asset_ref['hash']}.{output_format}"
        )
        path = root / filename
        if output_format == "png":
            if not path.exists():
                with open(source.file_path, "rb") as handle:
                    path.write_bytes(handle.read())
        elif not path.exists():
            with Image.open(source.file_path) as image:
                image.convert("RGB").save(path, format="JPEG", quality=95)
        return FileResponse(path, media_type="image/png" if output_format == "png" else "image/jpeg", filename=filename)

    path = root / f"social-kit-{kit.id}.zip"
    if not path.exists():
        manifest = {
            "platform": str(kit.target_channel),
            "format": str(kit.target_format),
            "profile_version": 1 if kit.target_channel == "instagram" and kit.target_format == "feed_portrait" else None,
            "cards": [],
        }
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for card in cards:
                asset_ref = dict(card["preview_asset_ref"])
                source = _render_asset(db, project_id, auth_ctx["workspace"].id, asset_ref["id"])
                filename = (
                    f"instagram-feed-portrait-{int(card['order']):02d}.png"
                    if kit.target_channel == "instagram" and kit.target_format == "feed_portrait"
                    else f"{int(card['order']):02d}-{card['card_id']}.png"
                )
                archive.write(source.file_path, arcname=filename)
                manifest["cards"].append({"order": int(card["order"]), "filename": filename})
            archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True, separators=(",", ":")))
    return FileResponse(path, media_type="application/zip", filename=path.name)
