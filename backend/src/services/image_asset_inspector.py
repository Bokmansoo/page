"""Deterministic inspection for user-supplied product images.

This module intentionally does not generate or alter images. It only records
metadata used by the visual planner and tells the UI when human review is
needed.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from src.db.models import Asset


ROLE_VALUES = {
    "product_main",
    "product_detail",
    "usage_scene",
    "components",
    "package",
    "spec_reference",
    "unknown",
}
QUALITY_VALUES = {"usable", "warning", "rejected"}
IDENTITY_VALUES = {"confirmed", "needs_review"}

MIN_RECOMMENDED_EDGE = 640
MIN_ASPECT_RATIO = 0.35
MAX_ASPECT_RATIO = 2.85


@dataclass(frozen=True)
class AssetInspection:
    asset_role: str
    role_confidence: float
    quality_status: str
    identity_status: str
    width: int | None
    height: int | None
    image_format: str | None
    quality_warnings: list[str]
    content_hash: str | None
    safe_crop_status: str


def recommend_asset_role(
    filename: str,
    source_type: str = "",
    file_path: str = "",
    ocr_text: str = "",
) -> tuple[str, float]:
    """Recommend a Sprint 2 role from stable, explainable local signals."""
    # Local temporary directories can contain accidental keywords such as
    # "inspector". Only a remote URL is a meaningful path-level signal.
    path_signal = file_path if file_path.startswith(("http://", "https://")) else ""
    text = " ".join((filename or "", source_type or "", path_signal, ocr_text or "")).lower()
    rules = (
        ("spec_reference", ("spec", "dimension", "manual", "label", "chart", "인증", "스펙", "규격", "설명서")),
        ("components", ("component", "accessory", "parts", "attachment", "구성품", "부속", "액세서리")),
        ("package", ("package", "packaging", "box", "unbox", "패키지", "박스", "포장")),
        ("product_detail", ("detail", "closeup", "close-up", "macro", "feature", "button", "head", "디테일", "근접", "기능")),
        ("usage_scene", ("lifestyle", "usage", "use", "scene", "room", "outdoor", "사용", "연출", "장면", "거실", "야외")),
        ("product_main", ("main", "hero", "front", "product", "대표", "정면", "상품", "제품")),
    )
    for role, keywords in rules:
        hits = sum(keyword in text for keyword in keywords)
        if hits:
            return role, round(min(0.9, 0.5 + hits * 0.12), 2)
    return "unknown", 0.25


def _safe_crop_status(width: int | None, height: int | None) -> str:
    """Return a conservative crop recommendation without altering the photo."""
    if not width or not height:
        return "needs_review"
    ratio = width / height
    if 0.75 <= ratio <= 1.5:
        return "safe"
    if 0.5 <= ratio <= 2.0:
        return "needs_review"
    return "not_recommended"


def _hash_file(file_path: str) -> str:
    digest = hashlib.sha256()
    with open(file_path, "rb") as image_file:
        for chunk in iter(lambda: image_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_asset(asset: Asset, db: Session) -> AssetInspection:
    """Inspect a local file with Pillow, without treating quality warnings as rejection."""
    role, confidence = recommend_asset_role(
        asset.filename,
        asset.source_type,
        asset.file_path,
        asset.ocr_text or "",
    )
    warnings: list[str] = []
    width: int | None = None
    height: int | None = None
    image_format: str | None = None
    content_hash: str | None = None

    if not asset.mime_type or not asset.mime_type.startswith("image/"):
        return AssetInspection(role, confidence, "rejected", "needs_review", None, None, None, ["NOT_AN_IMAGE"], None, "not_recommended")

    if not asset.file_path or asset.file_path.startswith(("http://", "https://")):
        return AssetInspection(
            role,
            confidence,
            "warning",
            "needs_review",
            None,
            None,
            None,
            ["REMOTE_IMAGE_NOT_DOWNLOADED"],
            None,
            "needs_review",
        )

    if not os.path.isfile(asset.file_path):
        # Older projects can retain an asset record after a local development
        # upload directory was cleaned. This is not proof that the photo itself
        # is damaged, so leave it available for seller review.
        return AssetInspection(role, confidence, "warning", "needs_review", None, None, None, ["IMAGE_FILE_NOT_AVAILABLE"], None, "needs_review")

    try:
        # verify catches truncated/corrupt images; reopen because Pillow closes
        # the decoder after verify().
        try:
            with Image.open(asset.file_path) as image:
                image.verify()
        except SyntaxError:
            # Some older valid-enough uploads (and common tiny fixture PNGs)
            # have a bad ancillary checksum. They can still be previewed, so
            # keep them for seller review instead of silently discarding them.
            warnings.append("IMAGE_INTEGRITY_WARNING")
        with Image.open(asset.file_path) as image:
            width, height = image.size
            image_format = image.format
        content_hash = _hash_file(asset.file_path)
    except (UnidentifiedImageError, OSError, ValueError):
        return AssetInspection(role, confidence, "rejected", "needs_review", None, None, None, ["IMAGE_FILE_CORRUPT"], None, "not_recommended")

    if width < MIN_RECOMMENDED_EDGE or height < MIN_RECOMMENDED_EDGE:
        warnings.append("LOW_RESOLUTION")
    ratio = width / height if height else 0
    if ratio < MIN_ASPECT_RATIO or ratio > MAX_ASPECT_RATIO:
        warnings.append("EXTREME_ASPECT_RATIO")
    safe_crop_status = _safe_crop_status(width, height)
    if safe_crop_status != "safe":
        warnings.append("SAFE_CROP_REVIEW_REQUIRED")
    duplicate = (
        db.query(Asset.id)
        .filter(
            Asset.project_id == asset.project_id,
            Asset.id != asset.id,
            Asset.content_hash == content_hash,
        )
        .first()
    )
    if duplicate:
        warnings.append("DUPLICATE_FILE")

    return AssetInspection(
        role,
        confidence,
        "warning" if warnings else "usable",
        "needs_review",
        width,
        height,
        image_format,
        warnings,
        content_hash,
        safe_crop_status,
    )


def apply_asset_inspection(asset: Asset, db: Session, *, preserve_manual_role: bool = True) -> Asset:
    inspection = inspect_asset(asset, db)
    if not (preserve_manual_role and asset.role_source == "manual" and asset.asset_role in ROLE_VALUES):
        asset.asset_role = inspection.asset_role
        asset.role_confidence = inspection.role_confidence
        asset.role_source = "auto"
    asset.quality_status = inspection.quality_status
    asset.identity_status = inspection.identity_status
    asset.width = inspection.width
    asset.height = inspection.height
    asset.image_format = inspection.image_format
    asset.quality_warnings = inspection.quality_warnings
    asset.content_hash = inspection.content_hash
    asset.safe_crop_status = inspection.safe_crop_status
    asset.classification_version = 2
    return asset


def refresh_representative_product_asset(project_id: str, db: Session) -> Asset | None:
    """Choose one non-manual representative, preferring the largest clear product photo."""
    assets = (
        db.query(Asset)
        .filter(Asset.project_id == project_id, Asset.mime_type.like("image/%"))
        .all()
    )
    manual = next(
        (asset for asset in assets if asset.is_representative and asset.representative_source == "manual"),
        None,
    )
    if manual:
        return manual

    candidates = [asset for asset in assets if asset.quality_status != "rejected"]
    if not candidates:
        return None

    role_weight = {
        "product_main": 4,
        "unknown": 3,
        "product_detail": 2,
        "usage_scene": 1,
        "components": 0,
        "package": 0,
        "spec_reference": 0,
    }

    def rank(asset: Asset) -> tuple[int, int, int, float]:
        # "상품이 분명함"은 API-free Sprint 2에서는 filename/OCR role signal과
        # quality status로만 판단한다. 사람/vision 검수는 identity_status로 남긴다.
        quality_bonus = 1 if asset.quality_status == "usable" else 0
        pixel_area = (asset.width or 0) * (asset.height or 0)
        return (
            role_weight.get(asset.asset_role, 0),
            quality_bonus,
            pixel_area,
            asset.role_confidence or 0.0,
        )

    selected = max(candidates, key=rank)
    for asset in assets:
        asset.is_representative = asset.id == selected.id
        if asset.id == selected.id:
            asset.representative_source = "auto"
            if asset.role_source != "manual":
                asset.asset_role = "product_main"
                asset.role_confidence = max(asset.role_confidence or 0.0, 0.7)
    return selected


def backfill_project_asset_metadata(project_id: str, db: Session) -> int:
    """Lazily inspect pre-Sprint-2 assets when their project is opened."""
    assets = db.query(Asset).filter(Asset.project_id == project_id).all()
    changed = 0
    for asset in assets:
        if asset.classification_version >= 2:
            continue
        apply_asset_inspection(asset, db)
        changed += 1
    if changed:
        refresh_representative_product_asset(project_id, db)
        db.commit()
    return changed
