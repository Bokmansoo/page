import os
import uuid
import zipfile
import logging
import datetime
import time
from html import escape
from typing import List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from PIL import Image, ImageDraw
from src.services.page_asset_policy import get_page_eligible_asset
from src.services.page_visual_contract import (
    lg10_renderer_direction_tokens,
    normalize_lg10_design_direction,
)
from src.services.prompt_intelligence_service import canonical_hash

logger = logging.getLogger(__name__)

PRESETS = {
    "coupang": {
        "width": 780,
        "max_height": 5000,
        "format": "PNG"
    },
    "smartstore": {
        "width": 860,
        "max_height": 20000,
        "format": "PNG"
    },
    "default": {
        "width": 800,
        "max_height": 5000,
        "format": "PNG"
    }
}


LG10_CANONICAL_RENDER_SCHEMA_VERSION = "lg10-canonical-render-v1"
LG11_RENDERER_PAGE_WIDTH = 760
LG11_BRAND_LOGO_GEOMETRY = {"x": 24, "y": 18, "width": 180, "height": 56}
LG11_BRAND_WATERMARK_SIZE = {"width": 132, "height": 64, "right": 18, "bottom": 18}
LG12_LAYOUT_EVIDENCE_SCHEMA_VERSION = "lg12-frozen-layout-evidence-v1"


def render_deterministic_social_card(
    output_path: str,
    *,
    role: str,
    card_id: str,
    semantic_hash: str,
    background: str = "#F3F4F6",
    accent: str = "#2563EB",
    width: int = 640,
    height: int = 360,
) -> None:
    """Write a stable local fixture image for the SocialKit fake renderer."""

    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 84), fill=accent)
    draw.text((24, 26), f"Sellform {role} card", fill="#FFFFFF")
    draw.text((24, 118), f"card:{card_id}", fill="#111827")
    draw.text((24, 154), f"render:{semantic_hash[:24]}", fill="#374151")
    image.save(output_path, format="PNG", optimize=False)


def lg12_renderer_typography_role_tokens(
    *,
    field: str,
    index: int,
    renderer_tokens: dict[str, Any],
    brand_tokens: dict[str, Any],
) -> dict[str, str]:
    """Return the renderer-owned typography contract for one frozen text role.

    These are named renderer/Brand-Kit tokens, not new pixel thresholds.  The
    evaluator imports this same contract so it never invents a second set of
    typography rules for a frozen page.
    """

    role = _lg12_copy_role(field, index)
    typography = dict(brand_tokens.get("typography") or {})
    return {
        "role": role,
        "font_token": "body_font",
        "font_family": str(typography.get("body_font") or ""),
        "size_token": str(renderer_tokens.get("title_scale") if role == "headline" else "renderer_body"),
        "weight_token": "renderer_h2" if role == "headline" else "renderer_body",
        "line_height_token": "renderer_text_1_65",
        "letter_spacing_token": "normal",
        "color_token": "accent" if role == "headline" else "text",
        # The canonical CSS has no role-specific alignment override.  Pin its
        # explicit default as a token instead of adding a numeric tolerance.
        "alignment_token": "renderer_text_left",
    }


def _lg12_copy_role(field: str, index: int) -> str:
    """Return the renderer role, without reading mutable copy artifacts."""

    value = field.lower()
    if "cta" in value or value in {"action", "action_text"}:
        return "cta"
    if "badge" in value or "label" in value:
        return "badge"
    if "subtitle" in value or "subheadline" in value or "subcopy" in value:
        return "subheadline"
    if "title" in value or "headline" in value or index == 0:
        return "headline"
    return "body"


def _lg12_layout_evidence(
    *,
    rendered_sections: list[dict[str, Any]],
    renderer_tokens: dict[str, Any],
    brand_tokens: dict[str, Any],
    canonical_page_assembly_input: dict[str, Any],
) -> dict[str, Any]:
    """Freeze bounded layout facts used by TASK-12.6.

    The evidence intentionally contains renderer tokens, stable IDs, and
    effective geometry only.  It never carries copy text, HTML, CSS, image
    bytes, or a mutable editor projection.
    """

    cursor = 0
    sections: list[dict[str, Any]] = []
    colors = dict(brand_tokens.get("color_tokens") or {})
    planning_refs = dict(canonical_page_assembly_input.get("planning_refs") or {})
    page_plan_ref = dict(planning_refs.get("page_plan") or {})
    brand_ref = dict(canonical_page_assembly_input.get("brand_kit_ref") or {})
    for section in rendered_sections:
        canvas = dict(section.get("canvas") or {})
        visible = canvas.get("is_visible", True)
        height = canvas.get("height_px")
        elements = [dict(item) for item in list(section.get("canvas_elements") or []) if isinstance(item, dict)]
        if not isinstance(height, int):
            height = max([160, *[
                int(item.get("y") or 0) + int(item.get("height") or 0)
                for item in elements if not bool(item.get("deleted"))
            ]])
        role_tokens = []
        for index, item in enumerate(list(section.get("text_layer") or [])):
            if not isinstance(item, dict):
                continue
            field = str(item.get("field") or "")
            role_tokens.append({"field": field, **lg12_renderer_typography_role_tokens(
                field=field, index=index, renderer_tokens=renderer_tokens, brand_tokens=brand_tokens,
            )})
        scene_ref = dict(section.get("scene_ref") or {})
        sections.append({
            "section_id": str(section.get("section_id") or ""),
            "sort_order": int(section.get("sort_order") or 0),
            "visible": bool(visible),
            "component_id": str(section.get("component_id") or ""),
            "layout_token": str(section.get("layout_token") or ""),
            "bounds": {"x": 0, "y": cursor, "width": LG11_RENDERER_PAGE_WIDTH, "height": int(height)},
            "spacing_token": str(renderer_tokens.get("renderer_token") or ""),
            "section_spacing_px": int(renderer_tokens.get("section_spacing") or 0),
            "padding_token": "renderer_section_padding_x_24",
            "alignment": {
                "expected_token": "renderer_text_left",
                "actual_token": "renderer_text_left",
            },
            "typography_roles": role_tokens,
            "scene": {
                "scene_id": str(scene_ref.get("scene_id") or ""),
                "scene_type": str(scene_ref.get("scene_type") or ""),
                "scene_order": scene_ref.get("scene_order"),
                "page_plan_ref": {
                    "id": str(scene_ref.get("page_plan_id") or page_plan_ref.get("id") or page_plan_ref.get("artifact_id") or ""),
                    "version": scene_ref.get("page_plan_version") or page_plan_ref.get("version") or page_plan_ref.get("artifact_version"),
                    "hash": str(scene_ref.get("page_plan_hash") or page_plan_ref.get("hash") or page_plan_ref.get("artifact_hash") or ""),
                },
            },
            "elements": [
                {
                    "element_id": str(item.get("element_id") or ""), "kind": str(item.get("kind") or ""),
                    "bounds": {key: item.get(key) for key in ("x", "y", "width", "height")},
                    "locked": bool(item.get("locked")), "group_id": item.get("group_id"),
                    "visible": not bool(item.get("deleted")),
                }
                for item in elements
            ],
        })
        if visible:
            cursor += int(height)
    payload = {
        "schema_version": LG12_LAYOUT_EVIDENCE_SCHEMA_VERSION,
        "renderer_version": LG10_CANONICAL_RENDER_SCHEMA_VERSION,
        # Filled after the renderer body has been assembled.  It is a hash of
        # the frozen renderer excluding this evidence, avoiding a hash cycle.
        "renderer_hash": "",
        "renderer_token": str(renderer_tokens.get("renderer_token") or ""),
        "renderer_width": LG11_RENDERER_PAGE_WIDTH,
        "section_spacing_px": int(renderer_tokens.get("section_spacing") or 0),
        "title_scale": str(renderer_tokens.get("title_scale") or ""),
        "page_plan_ref": {
            "id": str(page_plan_ref.get("id") or page_plan_ref.get("artifact_id") or ""),
            "version": page_plan_ref.get("version") or page_plan_ref.get("artifact_version"),
            "hash": str(page_plan_ref.get("hash") or page_plan_ref.get("artifact_hash") or ""),
        },
        "brand_kit_ref": {
            "id": str(brand_tokens.get("brand_kit_version_id") or brand_ref.get("brand_kit_version_id") or ""),
            "version": brand_tokens.get("brand_kit_version"),
            "hash": str(brand_tokens.get("brand_kit_hash") or brand_ref.get("brand_kit_hash") or ""),
        },
        "color_tokens": {key: str(colors.get(key) or "") for key in ("accent", "text", "surface", "muted_surface")},
        "typography": {"body_font": str(dict(brand_tokens.get("typography") or {}).get("body_font") or "")},
        # No WCAG-like number is invented here.  A future frozen Brand Kit or
        # renderer may pin a numeric contrast contract; absent one, the typed
        # token pair remains traceable but the contrast metric is skipped.
        "contrast": {
            "foreground_token": "text",
            "background_token": "surface",
            "minimum_ratio": brand_tokens.get("contrast_minimum"),
        },
        "sections": sections,
    }
    return payload


def lg11_effective_brand_geometry(
    *,
    brand_tokens: dict[str, Any],
    rendered_sections: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return the exact deterministic Brand Kit placements used by the renderer."""
    layer = dict(brand_tokens.get("asset_layer") or {})
    logo = layer.get("logo") if isinstance(layer.get("logo"), dict) else None
    watermark = layer.get("watermark") if isinstance(layer.get("watermark"), dict) else None
    cursor = 92 if logo else 0  # 18px top/bottom padding plus 56px logo box.
    section_offsets: dict[str, int] = {}
    for section in rendered_sections:
        canvas = dict(section.get("canvas") or {})
        if canvas.get("is_visible", True) is False:
            continue
        section_offsets[str(section.get("section_id") or "")] = cursor
        height = canvas.get("height_px")
        if not isinstance(height, int):
            element_bottoms = [
                int(item.get("y") or 0) + int(item.get("height") or 0)
                for item in section.get("canvas_elements") or []
                if isinstance(item, dict) and not item.get("deleted")
            ]
            height = max([160, *element_bottoms])
        cursor += height
    placements: dict[str, dict[str, int | str]] = {}
    if logo:
        placements["logo"] = {**LG11_BRAND_LOGO_GEOMETRY, "element_id": "brand:logo"}
    if watermark:
        placements["watermark"] = {
            "x": LG11_RENDERER_PAGE_WIDTH - LG11_BRAND_WATERMARK_SIZE["right"] - LG11_BRAND_WATERMARK_SIZE["width"],
            "y": max(0, cursor - LG11_BRAND_WATERMARK_SIZE["bottom"] - LG11_BRAND_WATERMARK_SIZE["height"]),
            "width": LG11_BRAND_WATERMARK_SIZE["width"],
            "height": LG11_BRAND_WATERMARK_SIZE["height"],
            "element_id": "brand:watermark",
        }
    return {"page_width": LG11_RENDERER_PAGE_WIDTH, "page_height": max(cursor, 1), "section_offsets": section_offsets, "placements": placements}


def _lg11_canvas_element_style(element: dict[str, Any]) -> str:
    """Render only validated, frozen Canvas geometry; never read a live draft."""
    required = ("element_id", "kind", "x", "y", "width", "height", "z_index", "locked")
    if not all(key in element for key in required) or not isinstance(element.get("element_id"), str):
        raise ValueError("LG-10 canonical renderer received an invalid Canvas element.")
    x, y, width, height, z_index = (element[key] for key in ("x", "y", "width", "height", "z_index"))
    if (element.get("kind") not in {"background", "text", "asset", "mask", "icon", "decorative"} or not isinstance(element.get("locked"), bool)
            or not all(isinstance(value, int) for value in (x, y, width, height, z_index))
            or not -2400 <= x <= 2400 or not -2400 <= y <= 2400 or not 1 <= width <= 760
            or not 1 <= height <= 2400 or not 0 <= z_index <= 100):
        raise ValueError("LG-10 canonical renderer received invalid Canvas element bounds.")
    position = "absolute" if element.get("kind") == "background" else "relative"
    return f"position:{position};left:{x}px;top:{y}px;width:{width}px;min-height:{height}px;z-index:{z_index}"


def render_lg10_canonical_page_html(
    *,
    canonical_page_assembly_input: dict[str, Any],
    page_assembly: dict[str, Any],
    copy_set: dict[str, Any],
    brand_tokens: dict[str, Any],
) -> dict[str, Any]:
    """Render only the immutable LG-10 structure into an editable text layer.

    Approved image identities remain a separate asset layer represented by
    stable data attributes. Resolving image URLs, screenshots, exports, and
    page versions belongs to later LG-10 tasks.
    """

    design_direction = normalize_lg10_design_direction(
        canonical_page_assembly_input.get("design_direction")
    )
    direction_tokens = lg10_renderer_direction_tokens(design_direction=design_direction)
    expected_renderer_token = direction_tokens["renderer_token"]
    canonical_sections = {
        str(section.get("section_id") or ""): dict(section or {})
        for section in (canonical_page_assembly_input.get("sections") or [])
        if isinstance(section, dict) and section.get("section_id")
    }
    assembly_sections = sorted(
        (dict(section or {}) for section in (page_assembly.get("sections") or []) if isinstance(section, dict)),
        key=lambda section: int(section.get("sort_order") or 0),
    )
    if not canonical_sections or len(assembly_sections) != len(canonical_sections):
        raise ValueError("LG-10 canonical renderer requires matching section contracts.")

    rendered_sections: list[dict[str, Any]] = []
    section_html: list[str] = []
    for expected_order, assembly_section in enumerate(assembly_sections):
        section_id = str(assembly_section.get("section_id") or "")
        canonical_section = canonical_sections.get(section_id)
        component_id = str(assembly_section.get("component_id") or "")
        layout_token = str(assembly_section.get("layout_token") or "")
        if (
            canonical_section is None
            or assembly_section.get("sort_order") != expected_order
            or component_id not in {"media_with_copy", "information_only"}
            or layout_token not in {"image_text", "spec_table"}
            or assembly_section.get("design_direction") != design_direction
            or assembly_section.get("renderer_token") != expected_renderer_token
        ):
            raise ValueError("LG-10 canonical renderer received an invalid component selection.")

        text_layer = []
        for field in list((canonical_section.get("copy_ref") or {}).get("fields") or []):
            if field not in copy_set:
                raise ValueError(f"LG-10 canonical renderer is missing immutable copy field: {field}")
            text_layer.append({"field": str(field), "text": str(copy_set[field] or "")})

        rendering_mode = str(
            canonical_section.get("rendering_mode")
            or ("approved_asset" if canonical_section.get("approved_assets") else "")
        )
        source_assets = (
            canonical_section.get("approved_assets") or []
            if rendering_mode == "approved_asset"
            else canonical_section.get("seller_owned_fallback_assets") or []
            if rendering_mode == "seller_owned_fallback"
            else []
        )
        source_asset_layer = [
            {
                "asset_id": str(asset.get("asset_id") or ""),
                "asset_content_hash": str(asset.get("asset_content_hash") or ""),
            }
            for asset in source_assets
            if isinstance(asset, dict) and asset.get("asset_id")
        ]
        if component_id == "information_only":
            source_asset_layer = []
        canvas = dict(canonical_section.get("canvas") or {})
        is_visible = canvas.get("is_visible", True)
        height_px = canvas.get("height_px")
        if not isinstance(is_visible, bool) or height_px is not None and (
            not isinstance(height_px, int) or height_px < 160 or height_px > 2400
        ):
            raise ValueError("LG-10 canonical renderer received invalid canvas section bounds.")

        canvas_elements = [dict(item or {}) for item in (canonical_section.get("canvas_elements") or [])]
        if len({str(item.get("element_id") or "") for item in canvas_elements}) != len(canvas_elements):
            raise ValueError("LG-10 canonical renderer received duplicate Canvas element IDs.")
        for element in canvas_elements:
            _lg11_canvas_element_style(element)
        visible_elements = [item for item in canvas_elements if not bool(item.get("deleted"))]
        elements_by_kind = {
            kind: sorted([item for item in visible_elements if item.get("kind") == kind], key=lambda item: (item["z_index"], item["element_id"]))
            for kind in {"background", "text", "asset", "mask", "icon", "decorative"}
        }
        asset_elements = elements_by_kind["asset"]
        text_elements = elements_by_kind["text"]
        background_elements = elements_by_kind["background"]
        asset_layer = (
            [{"asset_id": str(item.get("asset_id") or ""), "asset_content_hash": str(item.get("asset_content_hash") or "")}
             for item in asset_elements]
            if canvas_elements else source_asset_layer
        )
        if component_id == "information_only":
            asset_layer = []

        def canvas_attributes(element: dict[str, Any] | None) -> str:
            if element is None:
                return ""
            return ' data-canvas-element-id="{element_id}" data-layer-z="{z}" style="{style}"'.format(
                element_id=escape(str(element["element_id"]), quote=True), z=element["z_index"],
                style=_lg11_canvas_element_style(element),
            )

        asset_html = "".join(
            (
                '<figure class="sf-asset-layer" data-asset-id="{asset_id}" '
                'data-asset-content-hash="{asset_hash}"{canvas_attributes}></figure>'
            ).format(
                asset_id=escape(asset["asset_id"], quote=True),
                asset_hash=escape(asset["asset_content_hash"], quote=True),
                canvas_attributes=canvas_attributes(asset_elements[index]) if canvas_elements else "",
            )
            for index, asset in enumerate(asset_layer)
        )
        if layout_token == "spec_table":
            text_html = "<table class=\"sf-text-layer sf-spec-table\"><tbody>{}</tbody></table>".format(
                "".join(
                    '<tr data-copy-field="{field}"><th>{field}</th><td contenteditable="true">{text}</td></tr>'.format(
                        field=escape(item["field"], quote=True),
                        text=escape(item["text"]),
                    )
                    for item in text_layer
                )
            )
        else:
            title = text_layer[0]["text"] if text_layer else ""
            body_items = text_layer[1:] if text_layer else []
            text_html = (
                '<div class="sf-text-layer"><h2 contenteditable="true">{title}</h2>{body}</div>'
            ).format(
                title=escape(title),
                body="".join(
                    '<p data-copy-field="{field}" contenteditable="true">{text}</p>'.format(
                        field=escape(item["field"], quote=True), text=escape(item["text"])
                    )
                    for item in body_items
                ),
            )
        if canvas_elements:
            text_html = "".join(
                '<div class="sf-canvas-text-element"{attributes}>{text}</div>'.format(
                    attributes=canvas_attributes(text_element), text=text_html,
                ) for text_element in text_elements
            )
        background_html = "".join(
            '<div class="sf-canvas-background" aria-hidden="true"{attributes}></div>'.format(
                attributes=canvas_attributes(element),
            ) for element in background_elements
        )
        ornament_html = "".join(
            '<div class="sf-canvas-{kind}" aria-hidden="true" data-canvas-token="{token}"{attributes}></div>'.format(
                kind=escape(str(element["kind"]), quote=True), token=escape(str(element.get("token") or ""), quote=True),
                attributes=canvas_attributes(element),
            ) for kind in ("mask", "icon", "decorative") for element in elements_by_kind[kind]
        )
        if is_visible:
            height_attr = f' style="min-height:{height_px}px"' if height_px is not None else ""
            section_html.append(
            '<section class="sf-section sf-component-{component}" data-section-id="{section_id}" '
            'data-layout-token="{layout}"{height_attr}>{background_html}{ornament_html}{asset_html}{text_html}</section>'.format(
                component=escape(component_id, quote=True),
                section_id=escape(section_id, quote=True),
                layout=escape(layout_token, quote=True),
                height_attr=height_attr,
                background_html=background_html,
                ornament_html=ornament_html,
                asset_html=asset_html,
                text_html=text_html,
            )
            )
        rendered_section = {
            "section_id": section_id,
            "sort_order": expected_order,
            "component_id": component_id,
            "layout_token": layout_token,
            # Bounded PagePlan scene identity only; scene content remains in
            # its immutable planning artifact.
            "scene_ref": dict(canonical_section.get("scene_ref") or {}),
            "asset_layer": asset_layer,
            "text_layer": text_layer,
        }
        if canvas:
            rendered_section["canvas"] = {"is_visible": is_visible, "height_px": height_px}
        if canvas_elements:
            rendered_section["canvas_elements"] = canvas_elements
        rendered_sections.append(rendered_section)

    color_tokens = dict(brand_tokens.get("color_tokens") or {})
    typography_tokens = dict(brand_tokens.get("typography") or {})
    brand_asset_layer = dict(brand_tokens.get("asset_layer") or {})
    logo = brand_asset_layer.get("logo") if isinstance(brand_asset_layer.get("logo"), dict) else None
    watermark = (
        brand_asset_layer.get("watermark")
        if isinstance(brand_asset_layer.get("watermark"), dict)
        else None
    )
    brand_html = ""
    if logo:
        brand_html += (
            '<header class="sf-brand-logo" data-asset-id="{asset_id}" '
            'data-asset-content-hash="{asset_hash}" data-brand-placement="header" data-canvas-element-id="brand:logo"></header>'
        ).format(
            asset_id=escape(str(logo["asset_id"]), quote=True),
            asset_hash=escape(str(logo["asset_content_hash"]), quote=True),
        )
    if watermark:
        brand_html += (
            '<aside class="sf-brand-watermark" data-asset-id="{asset_id}" '
            'data-asset-content-hash="{asset_hash}" data-brand-placement="watermark" data-canvas-element-id="brand:watermark"></aside>'
        ).format(
            asset_id=escape(str(watermark["asset_id"]), quote=True),
            asset_hash=escape(str(watermark["asset_content_hash"]), quote=True),
        )
    css = (
        ".sf-page{{position:relative;max-width:760px;margin:0 auto;font-family:{font};color:{text};background:{surface};}}"
        ".sf-brand-logo{{display:flex;align-items:center;padding:18px 24px;background:{surface};}}"
        ".sf-brand-logo img{{display:block;max-width:180px;max-height:56px;object-fit:contain;}}"
        ".sf-brand-watermark{{position:absolute;right:18px;bottom:18px;z-index:1;opacity:.16;pointer-events:none;}}"
        ".sf-brand-watermark img{{display:block;max-width:132px;max-height:64px;object-fit:contain;}}"
        ".sf-section{{position:relative;overflow:hidden;padding:{spacing}px 24px;border-bottom:1px solid #e5e7eb;background:{surface};}}"
        ".sf-canvas-background{{pointer-events:none;background:{muted};}}"
        ".sf-canvas-mask,.sf-canvas-icon,.sf-canvas-decorative{{pointer-events:none;opacity:.18;}}"
        ".sf-asset-layer{{min-height:{media_height}px;margin:0 0 20px;background:{muted};border-radius:12px;}}"
        ".sf-canvas-text-element{{max-width:100%;}}"
        ".sf-text-layer{{line-height:1.65;white-space:pre-wrap;}}"
        ".sf-text-layer h2{{margin:0 0 12px;font-size:{title_size}px;color:{accent};}}"
        ".sf-text-layer p{{margin:0 0 10px;}}"
        ".sf-spec-table{{width:100%;border-collapse:collapse;}}"
        ".sf-spec-table th,.sf-spec-table td{{padding:10px;border-bottom:1px solid #dbe3ee;text-align:left;}}"
    ).format(
        font=escape(str(typography_tokens.get("body_font") or "system-ui, sans-serif"), quote=True),
        text=escape(str(color_tokens.get("text") or "#172033"), quote=True),
        surface=escape(str(color_tokens.get("surface") or "#ffffff"), quote=True),
        muted=escape(str(color_tokens.get("muted_surface") or "#eef2f7"), quote=True),
        accent=escape(str(color_tokens.get("accent") or "#0f766e"), quote=True),
        spacing=direction_tokens["section_spacing"],
        media_height=direction_tokens["media_min_height"],
        title_size={"compact": 24, "comfortable": 30, "balanced": 28}[direction_tokens["title_scale"]],
    )
    html = (
        '<main class="sf-page" data-design-direction="{direction}" '
        'data-brand-kit-version-id="{brand_version}">{brand_html}{sections}</main>'
    ).format(
        direction=escape(design_direction, quote=True),
        brand_version=escape(str(brand_tokens.get("brand_kit_version_id") or ""), quote=True),
        brand_html=brand_html,
        sections="".join(section_html),
    )
    brand_geometry = lg11_effective_brand_geometry(brand_tokens=brand_tokens, rendered_sections=rendered_sections)
    layout_evidence = _lg12_layout_evidence(
        rendered_sections=rendered_sections,
        renderer_tokens=direction_tokens,
        brand_tokens=brand_tokens,
        canonical_page_assembly_input=canonical_page_assembly_input,
    )
    rendering = {
        "schema_version": LG10_CANONICAL_RENDER_SCHEMA_VERSION,
        "design_direction": design_direction,
        "renderer_tokens": direction_tokens,
        "brand_tokens": brand_tokens,
        "brand_geometry": brand_geometry,
        "lg12_layout_evidence": layout_evidence,
        "sections": rendered_sections,
        "css": css,
        "html": html,
    }
    renderer_body = {key: value for key, value in rendering.items() if key != "lg12_layout_evidence"}
    layout_evidence["renderer_hash"] = canonical_hash(renderer_body)
    layout_evidence["evidence_hash"] = canonical_hash(layout_evidence)
    rendering["lg12_layout_evidence"] = layout_evidence
    return rendering

class PageRendererService:
    def __init__(self, upload_dir: str = "uploads"):
        self.upload_dir = upload_dir
        self.exports_dir = os.path.join(upload_dir, "exports")
        os.makedirs(self.exports_dir, exist_ok=True)

    def render_and_slice(self, db: Session, page: Any, preset_name: str) -> Tuple[str, List[str]]:
        """
        Renders the page to a full screenshot, slices it based on preset height limits,
        and packages the slices into a ZIP archive.
        
        Returns:
            Tuple[str, List[str]]: (ZIP file path, list of slice image paths)
        """
        preset = PRESETS.get(preset_name.lower(), PRESETS["default"])
        width = preset["width"]
        max_height = preset["max_height"]
        
        job_id = str(uuid.uuid4())
        
        # 1. HTML 컴파일
        html_content = self._compile_html(db, page, width)
        
        # 2. 이미지 렌더링 (Playwright 시도, 실패 시 Pillow Fallback)
        full_image_path = os.path.join(self.exports_dir, f"full_{job_id}.png")
        rendered_success = False
        
        # FACTORY_RAG_RUNTIME_MOCK과 유사하게, 환경 변수로 Mock 강제 가능
        force_mock = os.getenv("RENDERER_MOCK", "false").lower() == "true"
        
        if not force_mock:
            try:
                from playwright.sync_api import sync_playwright
                rendered_success = self._render_with_playwright(html_content, width, full_image_path)
            except Exception as e:
                logger.error(f"Playwright rendering failed, falling back to Mock Pillow renderer: {e}")
                rendered_success = False

        if not rendered_success:
            logger.info("Using Pillow Mock fallback to generate screenshot image.")
            self._render_with_pillow_fallback(page, width, full_image_path)

        # 3. Pillow로 스냅샷 분할 슬라이싱
        slice_paths = self._slice_image(full_image_path, max_height, job_id)
        
        # 4. ZIP 압축
        zip_filename = f"export_{preset_name}_{job_id}.zip"
        zip_path = os.path.join(self.exports_dir, zip_filename)
        
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            # 슬라이스 이미지 파일들을 추가
            for idx, slice_p in enumerate(slice_paths):
                arcname = f"section_{idx+1:02d}.png"
                zipf.write(slice_p, arcname)
            
            # 메타데이터 텍스트 파일 추가
            meta_content = (
                f"Sellform Export Metadata\n"
                f"Project: {page.project.name}\n"
                f"Date: {datetime.datetime.utcnow().isoformat()}\n"
                f"Preset: {preset_name}\n"
                f"Width: {width}px\n"
                f"Total Slices: {len(slice_paths)}\n"
            )
            zipf.writestr("metadata.txt", meta_content)
            
        # 전체 캡처 임시 이미지는 삭제
        self._remove_temporary_file(full_image_path)
            
        return zip_path, slice_paths

    def _remove_temporary_file(self, path: str) -> None:
        if not os.path.exists(path):
            return

        for attempt in range(3):
            try:
                os.remove(path)
                return
            except PermissionError:
                if attempt == 2:
                    logger.warning("Could not remove temporary render file: %s", path, exc_info=True)
                    return
                time.sleep(0.1)

    def _compile_html(self, db: Session, page: Any, width: int) -> str:
        theme_color = page.theme_color or "#3B82F6"
        font_family = page.font_family or "sans-serif"
        
        sections_html = []
        visible_sections = [sec for sec in page.sections if sec.is_visible]
        # sort_order 정렬
        visible_sections = sorted(visible_sections, key=lambda s: s.sort_order)
        
        for sec in visible_sections:
            img_html = ""
            if sec.image_asset_id:
                # 에셋 경로 확인
                asset = get_page_eligible_asset(
                    db, page.project_id, sec.image_asset_id
                )
                if asset and os.path.exists(asset.file_path):
                    # Playwright 로컬 파일 경로 사용
                    abs_path = os.path.abspath(asset.file_path)
                    file_url = f"file:///{abs_path.replace('\\', '/')}"
                    img_html = f'<img class="section-image" src="{file_url}" alt="section image"/>'
            
            if sec.section_type == "header":
                sections_html.append(f"""
                <div class="section section-header" style="background-color: {theme_color};">
                    <h1 style="margin:0; font-size: 32px;">{sec.title or ''}</h1>
                    <p style="margin-top: 15px; font-size: 18px; line-height:1.6; white-space: pre-wrap;">{sec.body_copy or ''}</p>
                    {img_html}
                </div>
                """)
            else:
                sections_html.append(f"""
                <div class="section">
                    <div class="section-title" style="border-left: 5px solid {theme_color}; padding-left: 10px;">{sec.title or ''}</div>
                    <div class="section-body">{sec.body_copy or ''}</div>
                    {img_html}
                </div>
                """)
                
        sections_str = "\n".join(sections_html)
        
        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{
    margin: 0;
    padding: 0;
    font-family: '{font_family}', sans-serif;
    background-color: #f9f9f9;
    color: #333;
    width: {width}px;
  }}
  .section {{
    padding: 40px 20px;
    border-bottom: 1px solid #eee;
    background-color: #fff;
    box-sizing: border-box;
    width: 100%;
  }}
  .section-header {{
    color: #fff;
    text-align: center;
    padding: 60px 20px;
  }}
  .section-title {{
    font-size: 24px;
    margin-bottom: 15px;
    font-weight: bold;
  }}
  .section-body {{
    font-size: 16px;
    line-height: 1.6;
    white-space: pre-wrap;
  }}
  .section-image {{
    max-width: 100%;
    height: auto;
    margin-top: 20px;
    display: block;
    margin-left: auto;
    margin-right: auto;
    border-radius: 8px;
  }}
</style>
</head>
<body>
  {sections_str}
</body>
</html>
"""
        return html

    def _render_with_playwright(self, html_content: str, width: int, output_path: str) -> bool:
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            # headless 브라우저 실행
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            # viewport 가로폭 설정, 세로는 기본으로 충분히 크게 설정
            page.set_viewport_size({"width": width, "height": 800})
            
            # HTML 내용 로드
            page.set_content(html_content)
            
            # 이미지 렌더링 대기를 위해 잠시 대기
            page.wait_for_timeout(1000)
            
            # fullPage 캡처
            page.screenshot(path=output_path, full_page=True)
            browser.close()
            
        return os.path.exists(output_path)

    def _render_with_pillow_fallback(self, page: Any, width: int, output_path: str):
        """
        Generates a dummy high-resolution image using Pillow listing the text content of the page.
        Used as a fallback when Playwright is unavailable.
        """
        # 임의로 긴 세로 크기를 계산
        visible_sections = [sec for sec in page.sections if sec.is_visible]
        section_count = len(visible_sections)
        estimated_height = max(800, section_count * 400 + 200)
        
        # 가짜 이미지 생성
        image = Image.new("RGB", (width, estimated_height), "#F3F4F6")
        draw = ImageDraw.Draw(image)
        
        # 테마 컬러 및 디자인 구성
        theme_color = page.theme_color or "#3B82F6"
        
        # 심플하게 각 섹션을 텍스트 상자로 렌더링
        y_offset = 20
        
        # 헤더 텍스트 드로잉
        draw.rectangle([(10, y_offset), (width - 10, y_offset + 80)], fill=theme_color)
        draw.text((20, y_offset + 30), f"Mock Rendering: {page.project.name}", fill="#FFFFFF")
        y_offset += 120
        
        for idx, sec in enumerate(visible_sections):
            box_height = 200
            # 섹션 박스
            draw.rectangle([(10, y_offset), (width - 10, y_offset + box_height)], fill="#FFFFFF", outline="#E5E7EB")
            
            # 텍스트
            draw.text((20, y_offset + 15), f"Section {idx+1}: {sec.section_type}", fill="#4B5563")
            draw.text((20, y_offset + 40), f"Title: {sec.title or 'N/A'}", fill="#1F2937")
            
            # 본문 말줄임 처리
            body = (sec.body_copy or "")[:60] + "..." if len(sec.body_copy or "") > 60 else (sec.body_copy or "")
            draw.text((20, y_offset + 70), f"Body: {body}", fill="#6B7280")
            
            if sec.image_asset_id:
                draw.rectangle([(20, y_offset + 120), (120, y_offset + box_height - 20)], fill="#D1D5DB")
                draw.text((30, y_offset + 130), "[Image Asset]", fill="#4B5563")
                
            y_offset += box_height + 20
            
        # 저장
        image.save(output_path, "PNG")
        image.close()

    def _slice_image(self, full_image_path: str, max_height: int, job_id: str) -> List[str]:
        image = Image.open(full_image_path)
        img_width, img_height = image.size
        
        slice_paths = []
        num_slices = (img_height + max_height - 1) // max_height
        
        for i in range(num_slices):
            top = i * max_height
            bottom = min((i + 1) * max_height, img_height)
            
            # 잘라내기 영역
            box = (0, top, img_width, bottom)
            cropped_image = image.crop(box)
            
            slice_filename = f"slice_{job_id}_{i+1:02d}.png"
            slice_path = os.path.join(self.exports_dir, slice_filename)
            cropped_image.save(slice_path, "PNG")
            cropped_image.close()
            slice_paths.append(slice_path)

        image.close()
        return slice_paths
