from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.auth import get_current_user_and_workspace, require_roles
from src.db.database import get_db
from src.db.models import BrandKit, BrandKitVersion, ProductProject
from src.services.brand_kit_service import (
    activate_version, create_kit, create_version, list_eligible_assets, resolved_project_version,
)

router = APIRouter(prefix="/brand-kits", tags=["brand-kits"])


class KitCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class VersionRequest(BaseModel):
    logo_asset_ids: list[str] = Field(default_factory=list, max_length=20)
    font_asset_ids: list[str] = Field(default_factory=list, max_length=20)
    color_tokens: dict[str, Any] = Field(default_factory=dict)
    typography: dict[str, Any] = Field(default_factory=dict)
    tone_of_voice: dict[str, Any] = Field(default_factory=dict)
    forbidden_terms: list[str] = Field(default_factory=list)
    cta_rules: dict[str, Any] = Field(default_factory=dict)
    image_style: dict[str, Any] = Field(default_factory=dict)
    layout_rules: dict[str, Any] = Field(default_factory=dict)
    background_rules: dict[str, Any] = Field(default_factory=dict)
    watermark_policy: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    asset_rights: dict[str, Any] = Field(default_factory=dict)


class ProjectOverrideRequest(VersionRequest):
    brand_kit_id: str
    activate: bool = True


def _view(version: BrandKitVersion | None) -> dict[str, Any] | None:
    if version is None:
        return None
    return {key: getattr(version, key) for key in (
        "id", "brand_kit_id", "workspace_id", "version", "status", "scope", "project_id",
        "logo_asset_ids", "font_asset_ids", "color_tokens", "typography", "tone_of_voice",
        "forbidden_terms", "cta_rules", "image_style", "layout_rules", "background_rules",
        "watermark_policy", "constraints", "asset_rights", "content_hash", "created_by", "activated_by",
        "created_at", "activated_at",
    )}


@router.get("")
def list_kits(db: Session = Depends(get_db), auth_ctx: dict = Depends(get_current_user_and_workspace)):
    workspace_id = auth_ctx["workspace"].id
    kits = db.query(BrandKit).filter_by(workspace_id=workspace_id).order_by(BrandKit.created_at.desc()).all()
    versions = db.query(BrandKitVersion).filter_by(workspace_id=workspace_id).order_by(
        BrandKitVersion.created_at.desc()).all()
    return {"kits": [{"id": kit.id, "name": kit.name, "created_at": kit.created_at} for kit in kits],
            "versions": [_view(item) for item in versions]}


@router.post("")
def create(payload: KitCreateRequest, db: Session = Depends(get_db),
           auth_ctx: dict = Depends(require_roles(["owner", "admin", "member"]))):
    try:
        kit = create_kit(db, auth_ctx["workspace"].id, auth_ctx["user"].id, payload.name)
    except Exception as exc:
        db.rollback(); raise HTTPException(status_code=409, detail="같은 이름의 Brand Kit가 이미 있습니다.") from exc
    return {"id": kit.id, "name": kit.name}


@router.get("/assets")
def assets(db: Session = Depends(get_db), auth_ctx: dict = Depends(get_current_user_and_workspace)):
    return [{"id": item.id, "filename": item.filename, "file_path": item.file_path,
             "mime_type": item.mime_type, "asset_role": item.asset_role,
             "usage_status": item.usage_status} for item in list_eligible_assets(db, auth_ctx["workspace"].id)]


@router.post("/{kit_id}/versions")
def version(kit_id: str, payload: VersionRequest, db: Session = Depends(get_db),
            auth_ctx: dict = Depends(require_roles(["owner", "admin", "member"]))):
    try:
        item = create_version(db, auth_ctx["workspace"].id, auth_ctx["user"].id, kit_id,
                              payload.model_dump(), scope="workspace")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _view(item)


@router.post("/versions/{version_id}/activate")
def activate(version_id: str, db: Session = Depends(get_db),
             auth_ctx: dict = Depends(require_roles(["owner", "admin"]))):
    try:
        return _view(activate_version(db, auth_ctx["workspace"].id, auth_ctx["user"].id, version_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/overrides")
def project_override(project_id: str, payload: ProjectOverrideRequest, db: Session = Depends(get_db),
                     auth_ctx: dict = Depends(require_roles(["owner", "admin", "member"]))):
    try:
        item = create_version(db, auth_ctx["workspace"].id, auth_ctx["user"].id,
                              payload.brand_kit_id, payload.model_dump(exclude={"brand_kit_id", "activate"}),
                              scope="project", project_id=project_id, activate=payload.activate)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _view(item)


@router.get("/projects/{project_id}/resolved")
def resolved(project_id: str, db: Session = Depends(get_db),
             auth_ctx: dict = Depends(get_current_user_and_workspace)):
    try:
        return {"version": _view(resolved_project_version(db, auth_ctx["workspace"].id, project_id))}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
