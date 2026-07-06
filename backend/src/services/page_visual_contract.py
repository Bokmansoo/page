from typing import Any

VISUAL_KINDS = {"image", "html_graphic"}
HTML_LAYOUTS = {"comparison_cards", "benefit_cards", "spec_table", "image_text", "hero_overlay"}

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

    if kind == "html_graphic":
        layout = payload.get("layout_variant")
        if layout not in HTML_LAYOUTS:
            issues.append("invalid_html_layout")
        if layout in {"comparison_cards", "benefit_cards"} and not payload.get("cards"):
            issues.append("html_cards_required")
        if layout == "spec_table" and not payload.get("table_rows"):
            issues.append("spec_rows_required")

    return issues
