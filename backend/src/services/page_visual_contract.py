from typing import Any

VISUAL_KINDS = {"image", "html_graphic", "composed_product"}
HTML_LAYOUTS = {
    "comparison_cards",
    "benefit_cards",
    "numeric_highlights",
    "spec_table",
    "steps",
    "checklist",
    "image_text",
    "hero_overlay",
}
COMPOSED_PRODUCT_LAYOUTS = {"hero_product_right", "hero_product_center"}
PRODUCT_FITS = {"contain"}
TEXT_SAFE_AREAS = {"left", "bottom"}
BACKGROUND_TOKENS = {"surface_mint", "surface_ink", "surface_sand"}

# LG-10 Page Assembly may select only these stable renderer-facing structures.
# The next renderer task owns their concrete HTML/CSS representation.
LG10_PAGE_ASSEMBLY_COMPONENTS = {
    "media_with_copy": "image_text",
    "information_only": "spec_table",
}

# LG-10.4 deliberately exposes a small, fixed renderer vocabulary.  The
# direction selects token values only; it never accepts a free-form layout.
LG10_DESIGN_DIRECTIONS = frozenset({"safe_information", "image_centric", "balanced_sale"})
LG10_DESIGN_DIRECTION_ALIASES = {
    # Existing storyboard choices are normalized before they enter the frozen
    # LG-10 contract.  The contract itself contains only the three values
    # above.
    "visual_story": "image_centric",
    "balanced_sales": "balanced_sale",
}
LG10_RENDERER_DIRECTION_TOKENS = {
    "safe_information": {
        "renderer_token": "safe_information_v1",
        "media_min_height": 220,
        "section_spacing": 32,
        "title_scale": "compact",
    },
    "image_centric": {
        "renderer_token": "image_centric_v1",
        "media_min_height": 360,
        "section_spacing": 40,
        "title_scale": "comfortable",
    },
    "balanced_sale": {
        "renderer_token": "balanced_sale_v1",
        "media_min_height": 280,
        "section_spacing": 36,
        "title_scale": "balanced",
    },
}

_SECTION_DEFAULT_LAYOUT = {
    "comparison": "comparison_cards",
    "detail_1": "benefit_cards",
    "guarantee": "spec_table",
    "product_info": "spec_table",
}


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _has_confirmed_fact_grounding(item: Any, *, fields: tuple[str, ...]) -> bool:
    """Ensure displayed product claims are traceable to confirmed facts."""
    if not isinstance(item, dict):
        return False
    if not all(_is_non_empty_string(item.get(field)) for field in fields):
        return False
    fact_ids = item.get("source_fact_ids")
    return (
        item.get("verification_status") == "confirmed"
        and isinstance(fact_ids, list)
        and bool(fact_ids)
        and all(_is_non_empty_string(fact_id) for fact_id in fact_ids)
    )


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
        if layout in {"comparison_cards", "benefit_cards"}:
            cards = payload.get("cards")
            if not isinstance(cards, list) or not cards:
                issues.append("html_cards_required")
            elif not all(_has_confirmed_fact_grounding(card, fields=("title", "body")) for card in cards):
                issues.append("html_card_grounding_required")
        if layout == "numeric_highlights":
            highlights = payload.get("highlights")
            if not isinstance(highlights, list) or not highlights:
                issues.append("numeric_highlights_required")
            elif not all(_has_confirmed_fact_grounding(item, fields=("label", "value")) for item in highlights):
                issues.append("numeric_highlight_grounding_required")
        if layout == "spec_table":
            rows = payload.get("table_rows")
            if not isinstance(rows, list) or not rows:
                issues.append("spec_rows_required")
            elif not all(_has_confirmed_fact_grounding(row, fields=("label", "value")) for row in rows):
                issues.append("spec_row_grounding_required")
        if layout == "steps":
            steps = payload.get("steps")
            if not isinstance(steps, list) or not steps:
                issues.append("html_steps_required")
            elif not all(
                isinstance(step, dict)
                and isinstance(step.get("step"), int)
                and step["step"] > 0
                and _has_confirmed_fact_grounding(step, fields=("title", "body"))
                for step in steps
            ):
                issues.append("html_step_grounding_required")
        if layout == "checklist":
            items = payload.get("items")
            if not isinstance(items, list) or not items:
                issues.append("html_checklist_required")
            elif not all(
                (
                    _has_confirmed_fact_grounding(item, fields=("text",))
                    or (
                        isinstance(item, dict)
                        and item.get("kind") == "seller_action"
                        and item.get("verification_status") == "action_required"
                        and item.get("source_fact_ids") == []
                        and _is_non_empty_string(item.get("text"))
                    )
                )
                for item in items
            ):
                issues.append("html_checklist_grounding_required")

    return issues


def normalize_lg10_design_direction(value: str | None) -> str:
    """Return the only design-direction values permitted by the LG-10 contract."""

    normalized = (value or "safe_information").strip().lower()
    normalized = LG10_DESIGN_DIRECTION_ALIASES.get(normalized, normalized)
    if normalized not in LG10_DESIGN_DIRECTIONS:
        raise ValueError(f"LG-10 does not support design direction: {value}")
    return normalized


def lg10_renderer_direction_tokens(*, design_direction: str | None) -> dict[str, Any]:
    """Return a copy of the fixed renderer tokens for one allowed direction."""

    return dict(LG10_RENDERER_DIRECTION_TOKENS[normalize_lg10_design_direction(design_direction)])


def select_lg10_page_assembly_component(
    *,
    rendering_mode: str,
    design_direction: str | None = None,
) -> dict[str, str]:
    """Return the sole allowed component/layout choice for an assembly section.

    This is intentionally deterministic: LG-10.2 persists a constrained
    structural choice, not generated markup or a free-form layout proposal.
    """

    direction = normalize_lg10_design_direction(design_direction)
    if rendering_mode in {"approved_asset", "seller_owned_fallback"}:
        component_id = "media_with_copy"
    elif rendering_mode == "information_only":
        component_id = "information_only"
    else:
        raise ValueError(f"LG-10 cannot select a component for rendering mode: {rendering_mode}")
    return {
        "component_id": component_id,
        "layout_token": LG10_PAGE_ASSEMBLY_COMPONENTS[component_id],
        "design_direction": direction,
        "renderer_token": str(LG10_RENDERER_DIRECTION_TOKENS[direction]["renderer_token"]),
    }
