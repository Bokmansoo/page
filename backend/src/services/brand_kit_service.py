from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.models import Asset, AuditLog, BrandKit, BrandKitVersion, ProductProject
from src.services.prompt_intelligence_service import canonical_hash


BRAND_FIELDS = (
    "logo_asset_ids", "font_asset_ids", "color_tokens", "typography", "tone_of_voice",
    "forbidden_terms", "cta_rules", "image_style", "layout_rules", "background_rules",
    "watermark_policy", "constraints", "asset_rights",
)
ELIGIBLE_ASSET_STATUSES = {"seller_owned", "rights_confirmed"}


def _validate_assets(db: Session, workspace_id: str, asset_ids: list[str]) -> None:
    if not asset_ids:
        return
    rows = db.query(Asset).join(ProductProject).filter(
        Asset.id.in_(asset_ids), ProductProject.workspace_id == workspace_id).all()
    if len({row.id for row in rows}) != len(set(asset_ids)):
        raise ValueError("다른 워크스페이스의 파일이 포함되어 있거나 파일을 찾을 수 없습니다.")
    blocked = [row.filename for row in rows if row.usage_status not in ELIGIBLE_ASSET_STATUSES]
    if blocked:
        raise ValueError("권리가 확인된 판매자 보유 파일만 Brand Kit에 사용할 수 있습니다: " + ", ".join(blocked))


def list_eligible_assets(db: Session, workspace_id: str) -> list[Asset]:
    return db.query(Asset).join(ProductProject).filter(
        ProductProject.workspace_id == workspace_id,
        Asset.usage_status.in_(ELIGIBLE_ASSET_STATUSES),
    ).order_by(Asset.created_at.desc()).all()


def create_kit(db: Session, workspace_id: str, actor_id: str, name: str) -> BrandKit:
    kit = BrandKit(workspace_id=workspace_id, name=name.strip(), created_by=actor_id)
    db.add(kit); db.flush()
    db.add(AuditLog(workspace_id=workspace_id, user_id=actor_id, action="brand_kit_created",
                    entity_type="brand_kit", entity_id=kit.id, payload={"name": kit.name}))
    db.commit(); db.refresh(kit)
    return kit


def create_version(db: Session, workspace_id: str, actor_id: str, kit_id: str,
                   payload: dict[str, Any], *, scope: str = "workspace",
                   project_id: str | None = None, activate: bool = False) -> BrandKitVersion:
    kit = db.query(BrandKit).filter_by(id=kit_id, workspace_id=workspace_id).first()
    if kit is None:
        raise LookupError("Brand Kit을 찾을 수 없습니다.")
    if scope not in {"workspace", "project"}:
        raise ValueError("Brand Kit 범위가 올바르지 않습니다.")
    if scope == "project":
        project = db.query(ProductProject).filter_by(id=project_id, workspace_id=workspace_id).first()
        if project is None:
            raise LookupError("프로젝트를 찾을 수 없습니다.")
    logo_ids = list(payload.get("logo_asset_ids") or [])
    font_ids = list(payload.get("font_asset_ids") or [])
    _validate_assets(db, workspace_id, logo_ids + font_ids)
    body = {key: payload.get(key, [] if key in {"logo_asset_ids", "font_asset_ids", "forbidden_terms"} else {})
            for key in BRAND_FIELDS}
    version_number = int(db.query(func.max(BrandKitVersion.version)).filter_by(brand_kit_id=kit.id).scalar() or 0) + 1
    version = BrandKitVersion(
        brand_kit_id=kit.id, workspace_id=workspace_id, version=version_number,
        status="draft", scope=scope, project_id=project_id,
        content_hash=canonical_hash({"scope": scope, "project_id": project_id, **body}),
        created_by=actor_id, **body,
    )
    db.add(version); db.flush()
    db.add(AuditLog(workspace_id=workspace_id, user_id=actor_id, action="brand_kit_version_created",
                    entity_type="brand_kit_version", entity_id=version.id,
                    payload={"version": version.version, "scope": scope, "project_id": project_id,
                             "content_hash": version.content_hash}))
    db.commit(); db.refresh(version)
    if activate:
        return activate_version(db, workspace_id, actor_id, version.id)
    return version


def activate_version(db: Session, workspace_id: str, actor_id: str, version_id: str) -> BrandKitVersion:
    version = db.query(BrandKitVersion).filter_by(id=version_id, workspace_id=workspace_id).with_for_update().first()
    if version is None:
        raise LookupError("Brand Kit 버전을 찾을 수 없습니다.")
    now = datetime.datetime.utcnow()
    if version.scope == "workspace":
        for old in db.query(BrandKitVersion).filter_by(
            workspace_id=workspace_id, scope="workspace", status="active").all():
            if old.id != version.id:
                old.status = "deprecated"; old.deprecated_at = now
    else:
        for old in db.query(BrandKitVersion).filter_by(
            workspace_id=workspace_id, scope="project", project_id=version.project_id, status="active").all():
            if old.id != version.id:
                old.status = "deprecated"; old.deprecated_at = now
    # The partial unique index permits one active version. Persist retirement
    # before promoting the replacement so statement ordering cannot violate it.
    db.flush()
    version.status = "active"; version.activated_by = actor_id; version.activated_at = now
    if version.scope == "project":
        project = db.query(ProductProject).filter_by(id=version.project_id, workspace_id=workspace_id).one()
        project.brand_kit_override_version_id = version.id
    db.add(AuditLog(workspace_id=workspace_id, user_id=actor_id, action="brand_kit_version_activated",
                    entity_type="brand_kit_version", entity_id=version.id,
                    payload={"version": version.version, "scope": version.scope,
                             "project_id": version.project_id, "content_hash": version.content_hash}))
    db.commit(); db.refresh(version)
    return version


def active_workspace_version(db: Session, workspace_id: str) -> BrandKitVersion | None:
    return db.query(BrandKitVersion).filter_by(
        workspace_id=workspace_id, scope="workspace", status="active").order_by(
        BrandKitVersion.activated_at.desc()).first()


def snapshot_project_brand_kit(db: Session, project: ProductProject) -> BrandKitVersion | None:
    if project.brand_kit_version_id:
        return db.query(BrandKitVersion).filter_by(id=project.brand_kit_version_id,
                                                   workspace_id=project.workspace_id).first()
    active = active_workspace_version(db, project.workspace_id)
    if active is not None:
        project.brand_kit_version_id = active.id
        db.add(project); db.flush()
    return active


def resolved_project_version(db: Session, workspace_id: str, project_id: str) -> BrandKitVersion | None:
    project = db.query(ProductProject).filter_by(id=project_id, workspace_id=workspace_id).first()
    if project is None:
        raise LookupError("프로젝트를 찾을 수 없습니다.")
    version_id = project.brand_kit_override_version_id or project.brand_kit_version_id
    if version_id:
        return db.query(BrandKitVersion).filter_by(id=version_id, workspace_id=workspace_id).first()
    return snapshot_project_brand_kit(db, project)
