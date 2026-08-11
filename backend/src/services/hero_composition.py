"""Deterministic, API-free HERO composition payloads.

This service never edits a seller's product photograph.  It only decides how
the shared HTML/CSS renderer should arrange the original image, copy and
decorative shapes.
"""
from __future__ import annotations

from typing import Any


HERO_BLOCKING_WARNINGS = {
    "LOW_RESOLUTION",
    "EXTREME_ASPECT_RATIO",
    "DUPLICATE_FILE",
    "IMAGE_INTEGRITY_WARNING",
}


def _value(asset: Any, key: str, default: Any = None) -> Any:
    return asset.get(key, default) if isinstance(asset, dict) else getattr(asset, key, default)


def build_composed_product_payload(asset: Any, template_key: str | None = None) -> dict[str, Any] | None:
    """Return a safe HERO payload for a usable product image, otherwise None."""
    if not asset or not str(_value(asset, "mime_type", "")).startswith("image/"):
        return None
    # Sprint 3 composes the one representative product photo confirmed by the
    # Sprint 2 classifier/seller.  Detail, package and unconfirmed images stay
    # available through the compatible legacy image renderer.
    if not _value(asset, "is_representative", False):
        return None
    if _value(asset, "asset_role", "unknown") != "product_main":
        return None
    if _value(asset, "quality_status", "warning") == "rejected":
        return None
    warnings = set(_value(asset, "quality_warnings", []) or [])
    if HERO_BLOCKING_WARNINGS.intersection(warnings):
        return None

    safe_crop = _value(asset, "safe_crop_status", "needs_review")
    style = (template_key or "").lower()
    # Narrow or uncertain source photos get a vertical, center-focused mobile
    # composition.  Clear photos keep the commerce-standard split HERO.
    use_center_layout = safe_crop != "safe" or style in {"minimal", "editorial"}
    if use_center_layout:
        layout_variant = "hero_product_center"
        text_safe_area = "bottom"
    else:
        layout_variant = "hero_product_right"
        text_safe_area = "left"

    background_token = "surface_mint"
    if "premium" in style or "dark" in style:
        background_token = "surface_ink"
    elif "warm" in style or "natural" in style:
        background_token = "surface_sand"

    return {
        "layout_variant": layout_variant,
        "product_fit": "contain",
        "text_safe_area": text_safe_area,
        "background_token": background_token,
        "decoration_tokens": ["soft_circle", "accent_line"],
    }


def apply_composed_product_hero(page: Any, db: Any, template_key: str | None = None) -> bool:
    """Upgrade legacy default HEROs when a usable real photo is available.

    A deliberately customized HERO remains untouched; only the old default
    `hero_overlay`/empty payload is upgraded.
    """
    from src.db.models import Asset

    changed = False
    for section in getattr(page, "sections", []) or []:
        if section.section_type != "hero" or not section.image_asset_id:
            continue
        payload = dict(section.visual_payload or {})
        legacy_default = section.visual_kind in {None, "image"} and payload.get(
            "layout_variant", "hero_overlay"
        ) == "hero_overlay"
        if not legacy_default:
            continue
        asset = db.query(Asset).filter(Asset.id == section.image_asset_id).first()
        composed_payload = build_composed_product_payload(asset, template_key)
        if not composed_payload:
            continue
        # Composition is a rendering upgrade, not a new seller selection.
        # Keep server-owned review/selection evidence that was persisted when
        # the current HERO asset was explicitly chosen.  Dropping this data
        # made an already-confirmed HERO block unrelated section edits and
        # exports again after the visual backfill ran.
        for key in (
            "low_quality_hero_confirmed",
            "ux2c_selection_state",
            "asset_id",
        ):
            if key in payload:
                composed_payload[key] = payload[key]
        section.visual_kind = "composed_product"
        section.visual_payload = composed_payload
        changed = True
    return changed
