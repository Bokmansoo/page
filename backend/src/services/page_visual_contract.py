from typing import Any


class LG11CanvasSafetyError(ValueError):
    """Raised when a frozen LG-11 Canvas snapshot cannot be previewed/exported."""

    def __init__(self, result: dict[str, Any]):
        self.result = result
        super().__init__("LG-11 Canvas safety validation blocked this frozen version.")

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


def validate_lg11_canvas_safety(
    *,
    version_snapshot: dict[str, Any],
    channel: str = "smartstore",
) -> dict[str, Any]:
    """Validate frozen Canvas geometry for a channel without reading live drafts.

    Canvas coordinates are renderer-local (the renderer owns its padding), so
    the safe rectangle is the full rendered section width.  Backgrounds may
    intentionally bleed to that rectangle; every other visible element must
    remain inside it.  The returned value is deliberately JSON-friendly so
    preview and every export endpoint can use the exact same gate.
    """
    from src.services.channel_export_service import get_channel_preset

    snapshot = dict(version_snapshot or {})
    lg10 = dict(snapshot.get("lg10") or {})
    rendering = dict(lg10.get("canonical_rendering") or {})
    canonical = dict(lg10.get("canonical_page_assembly_input") or {})
    # LG-10 versions without a Canvas child remain governed by their existing
    # immutable export rules.  Do not retroactively invent Canvas geometry.
    if not isinstance(snapshot.get("lg11"), dict):
        return {"schema_version": "lg11-canvas-safety-v1", "channel": channel, "safe": True, "issues": [], "checked": False}
    try:
        preset = get_channel_preset(channel)
    except ValueError:
        return {
            "schema_version": "lg11-canvas-safety-v1", "channel": channel, "safe": False, "checked": True,
            "issues": [{"code": "unsupported_channel", "reason": "Unsupported channel safe-area contract."}],
        }

    from src.services.renderer import lg11_effective_brand_geometry

    width = min(760, int(preset.width))
    issues: list[dict[str, Any]] = []
    sections = list(rendering.get("sections") or canonical.get("sections") or [])
    initial_brand_layer = dict(dict(rendering.get("brand_tokens") or {}).get("asset_layer") or {})
    # This is the same 18 + 56 + 18 header box used by the renderer helper.
    page_height = 92 if isinstance(initial_brand_layer.get("logo"), dict) else 0
    visible_boxes: list[dict[str, Any]] = []
    for index, raw in enumerate(sections):
        section = dict(raw or {})
        section_id = str(section.get("section_id") or section.get("id") or "")
        canvas = dict(section.get("canvas") or {})
        visible = canvas.get("is_visible", True)
        if not isinstance(visible, bool):
            issues.append({"code": "invalid_section_visibility", "reason": "Section visibility is invalid.", "section_id": section_id})
            continue
        if not visible:
            # A hidden section and its children are not in the frozen rendered
            # output, therefore they cannot create a visible overflow.
            continue
        raw_height = canvas.get("height_px")
        elements = [dict(item or {}) for item in list(section.get("canvas_elements") or []) if not bool(dict(item or {}).get("deleted"))]
        content_height = max([160, *[int(item.get("y", 0)) + int(item.get("height", 0)) for item in elements]])
        section_height = int(raw_height) if isinstance(raw_height, int) else content_height
        if section_height < 160 or section_height > 2400:
            issues.append({"code": "section_height_out_of_bounds", "reason": "Section height violates the channel contract.", "section_id": section_id})
            continue
        section_top = page_height
        page_height += section_height
        for element in elements:
            element_id = str(element.get("element_id") or "")
            try:
                x, y = int(element["x"]), int(element["y"])
                element_width, element_height = int(element["width"]), int(element["height"])
            except (KeyError, TypeError, ValueError):
                issues.append({"code": "invalid_element_geometry", "reason": "Element geometry is invalid.", "section_id": section_id, "element_id": element_id})
                continue
            if x < 0 or y < 0 or x + element_width > width or y + element_height > section_height:
                issues.append({"code": "element_overflow", "reason": "Element exceeds the channel safe area.", "section_id": section_id, "element_id": element_id})
            if element.get("kind") != "background":
                visible_boxes.append({
                    "section_id": section_id,
                    "element_id": element_id,
                    "kind": str(element.get("kind") or ""),
                    "x": x,
                    "y": section_top + y,
                    "width": element_width,
                    "height": element_height,
                    "allowed_overlap_with": list(element.get("allowed_overlap_with") or []),
                })
    if page_height > 30000:
        issues.append({"code": "page_height_out_of_bounds", "reason": "Page height exceeds the channel contract."})

    # Final spec must be visible and last in the frozen rendering, matching
    # the commit-time Canvas invariant rather than any mutable editor state.
    section_ids = [str(dict(item or {}).get("section_id") or dict(item or {}).get("id") or "") for item in sections]
    specs = [idx for idx, section_id in enumerate(section_ids) if section_id == "specs" or section_id.endswith("_specs")]
    if specs:
        spec_index = specs[-1]
        spec_canvas = dict(dict(sections[spec_index] or {}).get("canvas") or {})
        if len(specs) != 1 or spec_index != len(sections) - 1 or not spec_canvas.get("is_visible", True):
            issues.append({"code": "final_spec_position", "reason": "Final specification section must remain visible and last.", "section_id": section_ids[spec_index]})

    # The renderer freezes these placements.  Older snapshots derive them from
    # the same renderer helper, never from mutable Brand Kit state.
    brand_layer = dict(dict(rendering.get("brand_tokens") or {}).get("asset_layer") or {})
    brand_geometry = dict(rendering.get("brand_geometry") or {})
    if not brand_geometry:
        brand_geometry = lg11_effective_brand_geometry(
            brand_tokens=dict(rendering.get("brand_tokens") or {}),
            rendered_sections=[dict(item or {}) for item in sections],
        )
    placements = dict(brand_geometry.get("placements") or {})
    effective_page_height = max(page_height, int(brand_geometry.get("page_height") or 0), 1)
    for role in ("logo", "watermark"):
        identity = brand_layer.get(role)
        if not isinstance(identity, dict):
            continue
        # A frozen renderer placement takes precedence; legacy snapshots use
        # a stored canvas geometry only where the renderer had already frozen
        # it, otherwise deterministic renderer placement is used.
        geometry = placements.get(role) or identity.get("canvas_geometry")
        if not isinstance(geometry, dict):
            issues.append({"code": "invalid_brand_geometry", "reason": "Brand Kit renderer geometry is unavailable.", "brand_role": role})
            continue
        try:
            x, y, item_width, item_height = (int(geometry[key]) for key in ("x", "y", "width", "height"))
        except (KeyError, TypeError, ValueError):
            issues.append({"code": "invalid_brand_geometry", "reason": "Brand Kit geometry is invalid.", "brand_role": role})
            continue
        element_id = str(geometry.get("element_id") or f"brand:{role}")
        if x < 0 or y < 0 or x + item_width > width or y + item_height > effective_page_height:
            issues.append({"code": "brand_overflow", "reason": "Brand Kit asset exceeds the channel safe area.", "brand_role": role, "asset_id": identity.get("asset_id")})
        visible_boxes.append({"section_id": "__brand__", "element_id": element_id, "kind": role, "x": x, "y": y, "width": item_width, "height": item_height, "allowed_overlap_with": []})

    def overlaps(left: dict[str, Any], right: dict[str, Any]) -> bool:
        return (
            left["x"] < right["x"] + right["width"]
            and right["x"] < left["x"] + left["width"]
            and left["y"] < right["y"] + right["height"]
            and right["y"] < left["y"] + left["height"]
        )

    def intentionally_allowed(left: dict[str, Any], right: dict[str, Any]) -> bool:
        if left["kind"] == "background" or right["kind"] == "background":
            return True
        # Only decoration/mask/icon relationships are allowed to layer over
        # content; arbitrary text/asset overlap never becomes silently safe.
        return (
            left["kind"] in {"mask", "icon", "decorative"}
            and right["element_id"] in left["allowed_overlap_with"]
        ) or (
            right["kind"] in {"mask", "icon", "decorative"}
            and left["element_id"] in right["allowed_overlap_with"]
        )

    def renderer_flow_pair(left: dict[str, Any], right: dict[str, Any]) -> bool:
        """Legacy default text/asset coordinates are relative-flow, not overlay boxes."""
        kinds = {left["kind"], right["kind"]}
        if kinds != {"text", "asset"}:
            return False
        text = left if left["kind"] == "text" else right
        asset = right if left["kind"] == "text" else left
        return (
            text["element_id"] == f"{text['section_id']}:text"
            and asset["element_id"].startswith(f"{asset['section_id']}:asset")
            and text["y"] == asset["y"]
        )

    for index, left in enumerate(visible_boxes):
        for right in visible_boxes[index + 1:]:
            if overlaps(left, right) and not intentionally_allowed(left, right) and not renderer_flow_pair(left, right):
                issues.append({
                    "code": "element_overlap",
                    "reason": "Visible elements overlap outside an allowed Canvas relationship.",
                    "section_id": left["section_id"],
                    "element_id": left["element_id"],
                    "conflicting_element_id": right["element_id"],
                })
    return {
        "schema_version": "lg11-canvas-safety-v1", "channel": channel, "safe": not issues, "checked": True,
        "viewport": {"width": width, "max_segment_height": int(preset.max_segment_height)}, "issues": issues,
    }


def ensure_lg11_canvas_safe(*, version_snapshot: dict[str, Any], channel: str = "smartstore") -> dict[str, Any]:
    result = validate_lg11_canvas_safety(version_snapshot=version_snapshot, channel=channel)
    if not result["safe"]:
        raise LG11CanvasSafetyError(result)
    return result


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
