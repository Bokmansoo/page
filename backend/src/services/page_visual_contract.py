from typing import Any

VISUAL_KINDS = {"image", "html_graphic", "composed_product"}
HTML_LAYOUTS = {"comparison_cards", "benefit_cards", "spec_table", "image_text", "hero_overlay"}
COMPOSED_PRODUCT_LAYOUTS = {"hero_product_right", "hero_product_center"}
PRODUCT_FITS = {"contain"}
TEXT_SAFE_AREAS = {"left", "bottom"}
BACKGROUND_TOKENS = {"surface_mint", "surface_ink", "surface_sand"}

_SECTION_DEFAULT_LAYOUT = {
    "comparison": "comparison_cards",
    "detail_1": "benefit_cards",
    "guarantee": "spec_table",
}


def normalize_visual(
    *,
    section_type: str,
    image_asset_id: str | None,
    visual_kind: str | None,
    visual_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Normalize a section's visual contract into canonical form."""
    kind = visual_kind or ("image" if image_asset_id else "html_graphic")
    payload = dict(visual_payload or {})
    payload.setdefault(
        "layout_variant",
        _SECTION_DEFAULT_LAYOUT.get(section_type, "image_text"),
    )
    return {
        "visual_kind": kind,
        "visual_payload": payload,
        "image_asset_id": image_asset_id,
    }


def validate_visual(visual: dict[str, Any]) -> list[str]:
    """Validate a canonical visual contract. Returns a list of issue codes."""
    kind = visual.get("visual_kind", "")
    payload = visual.get("visual_payload") or {}
    issues: list[str] = []

    if kind not in VISUAL_KINDS:
        return ["invalid_visual_kind"]

    if kind == "image" and not visual.get("image_asset_id"):
        issues.append("image_asset_required")

    if kind == "composed_product":
        if not visual.get("image_asset_id"):
            issues.append("image_asset_required")
        if payload.get("layout_variant") not in COMPOSED_PRODUCT_LAYOUTS:
            issues.append("invalid_composed_product_layout")
        if payload.get("product_fit") not in PRODUCT_FITS:
            issues.append("invalid_product_fit")
        if payload.get("text_safe_area") not in TEXT_SAFE_AREAS:
            issues.append("invalid_text_safe_area")
        if payload.get("background_token") not in BACKGROUND_TOKENS:
            issues.append("invalid_background_token")
        if not isinstance(payload.get("decoration_tokens"), list):
            issues.append("decoration_tokens_required")

    if kind == "html_graphic":
        layout = payload.get("layout_variant")
        if layout not in HTML_LAYOUTS:
            issues.append("invalid_html_layout")
        if layout in {"comparison_cards", "benefit_cards"} and not payload.get("cards"):
            issues.append("html_cards_required")
        if layout == "spec_table" and not payload.get("table_rows"):
            issues.append("spec_rows_required")

    return issues
