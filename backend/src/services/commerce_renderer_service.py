"""Sprint 6 immutable commerce-renderer contract.

The application has more than one UI that can show a detail page.  This
service creates one serialisable artifact from a page snapshot so preview,
editor and export can agree on the exact same visible section order.  It does
not write to the database; callers persist the returned snapshot as a normal
page version when required.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable


FINAL_SPEC_TYPES = {
    "specifications",
    "final_specifications",
    "product_specifications",
    "product_info",
    "product_information",
}
REFERENCE_ONLY_SOURCE_TYPES = {"sourced", "url-extracted", "url-imported"}

# The renderer owns these tokens rather than the browser editor.  A saved
# artifact can therefore be rendered consistently by preview and export even
# when the editor UI changes later.
TEMPLATE_TOKENS: dict[str, dict[str, Any]] = {
    "commerce_story": {
        "name": "균형 판매형",
        "canvas_width": 760,
        "section_gap": 36,
        "title_scale": "balanced",
        "surface": "clean",
        "accent": "#0f766e",
    },
    "commerce_story_soft": {
        "name": "부드러운 신뢰형",
        "canvas_width": 760,
        "section_gap": 44,
        "title_scale": "comfortable",
        "surface": "soft",
        "accent": "#0f766e",
    },
    "commerce_story_bold": {
        "name": "강조 판매형",
        "canvas_width": 760,
        "section_gap": 28,
        "title_scale": "strong",
        "surface": "contrast",
        "accent": "#0f766e",
    },
}


@dataclass(frozen=True)
class RenderIssue:
    code: str
    message: str
    section_id: str | None = None


def _value(source: Any, key: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _section_snapshot(section: Any) -> dict[str, Any]:
    visual_payload = dict(_value(section, "visual_payload", {}) or {})
    return {
        "id": _value(section, "id"),
        "section_type": _value(section, "section_type") or _value(section, "key"),
        "title": _value(section, "title") or "",
        "body_copy": _value(section, "body_copy") or _value(section, "body") or "",
        "associated_fact_ids": list(_value(section, "associated_fact_ids", []) or []),
        "image_asset_id": _value(section, "image_asset_id"),
        "visual_kind": _value(section, "visual_kind") or "html_graphic",
        "visual_payload": visual_payload,
        # This is intentionally stored with a section snapshot.  It lets a
        # later reviewer distinguish a seller's own edit from an AI proposal.
        "copy_provenance": visual_payload.get("copy_provenance", "seller"),
        "sort_order": int(_value(section, "sort_order", 0) or 0),
        "is_visible": bool(_value(section, "is_visible", True)),
        "facts_stale": bool(_value(section, "facts_stale", False)),
    }


def build_commerce_artifact(
    page: Any,
    assets: Iterable[Any] = (),
    *,
    template_key: str = "commerce_story",
) -> dict[str, Any]:
    """Build a deterministic, renderer-ready artifact and its blockers.

    Supplier captures (`reference_only`) are accepted as generation inputs but
    never as final page visuals.  A section with factual copy must retain fact
    links; stale facts and ungrounded numeric claims are explicitly surfaced.
    """
    if template_key not in TEMPLATE_TOKENS:
        template_key = "commerce_story"
    template_tokens = TEMPLATE_TOKENS[template_key]
    asset_by_id = {str(_value(asset, "id")): asset for asset in assets}
    sections = sorted(
        (_section_snapshot(section) for section in (_value(page, "sections", []) or [])),
        key=lambda item: item["sort_order"],
    )
    visible = [item for item in sections if item["is_visible"]]
    issues: list[RenderIssue] = []
    warnings: list[RenderIssue] = []

    final_positions = [
        index for index, item in enumerate(visible) if item["section_type"] in FINAL_SPEC_TYPES
    ]
    if not final_positions:
        issues.append(RenderIssue("final_specification_missing", "최종 제품 사양·고지 블록이 필요합니다."))
    elif final_positions[-1] != len(visible) - 1:
        item = visible[final_positions[-1]]
        issues.append(
            RenderIssue(
                "final_specification_not_last",
                "최종 제품 사양·고지 블록은 마지막 표시 섹션이어야 합니다.",
                item["id"],
            )
        )

    image_usage: dict[str, list[str]] = {}
    numeric_pattern = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)?\s*(?:%|mm|cm|mAh|W|V|kg|g|분|시간|개|℃|°C)")
    for item in visible:
        section_id = item["id"]
        combined_copy = f"{item['title']} {item['body_copy']}"
        if len(item["title"].strip()) > 72:
            warnings.append(RenderIssue("title_wrap_review", "긴 제목은 모바일 줄바꿈을 확인해 주세요.", section_id))
        if not item["title"].strip() and not item["body_copy"].strip():
            warnings.append(RenderIssue("blank_section", "내용이 비어 있는 표시 섹션입니다.", section_id))
        if item["facts_stale"]:
            issues.append(RenderIssue("stale_fact", "연결된 사실이 변경되어 문구 재검토가 필요합니다.", section_id))
        if numeric_pattern.search(combined_copy) and not item["associated_fact_ids"]:
            issues.append(
                RenderIssue(
                    "ungrounded_numeric_copy",
                    "수치가 포함된 문구에는 확인된 사실 연결이 필요합니다.",
                    section_id,
                )
            )
        asset_id = item["image_asset_id"]
        if asset_id:
            image_usage.setdefault(str(asset_id), []).append(str(section_id))
            asset = asset_by_id.get(str(asset_id))
            source_type = str(_value(asset, "source_type", "")) if asset else ""
            usage_status = str(_value(asset, "usage_status", "")) if asset else ""
            if source_type in REFERENCE_ONLY_SOURCE_TYPES or usage_status == "reference_only":
                issues.append(
                    RenderIssue(
                        "supplier_reference_not_renderable",
                        "공급처 원본 캡처는 최종 상세페이지에 직접 사용할 수 없습니다.",
                        section_id,
                    )
                )
            crop = item["visual_payload"].get("crop")
            if crop:
                try:
                    crop_is_valid = (
                        isinstance(crop, dict)
                        and 0 <= float(crop.get("x", 0.5)) <= 1
                        and 0 <= float(crop.get("y", 0.5)) <= 1
                    )
                except (TypeError, ValueError):
                    crop_is_valid = False
                if not crop_is_valid:
                    issues.append(RenderIssue("invalid_crop", "이미지 크롭 위치는 이미지 안쪽 범위여야 합니다.", section_id))
        elif item["visual_kind"] in {"image", "composed_product"}:
            issues.append(RenderIssue("missing_visual", "이미지 블록에 최종 이미지가 없습니다.", section_id))

    for asset_id, section_ids in image_usage.items():
        if len(section_ids) > 1:
            for section_id in section_ids:
                issues.append(
                    RenderIssue(
                        "repeated_visual",
                        "같은 이미지는 한 개의 스토리 섹션에만 사용하세요.",
                        section_id,
                    )
                )

    payload = {
        "artifact_version": "commerce-renderer-v1",
        "template_key": template_key,
        "template_tokens": template_tokens,
        "theme_color": _value(page, "theme_color", "#0f766e"),
        "font_family": _value(page, "font_family", "sans-serif"),
        "sections": sections,
        "renderer_rules": {
            "editor_ui_excluded": True,
            "wait_for_images_and_fonts": True,
            "fixed_canvas_width": template_tokens["canvas_width"],
            "supplier_reference_output_forbidden": True,
        },
    }
    digest_source = repr(payload).encode("utf-8")
    payload["artifact_hash"] = hashlib.sha256(digest_source).hexdigest()
    payload["ready"] = not issues
    payload["blockers"] = [issue.__dict__ for issue in issues]
    payload["warnings"] = [issue.__dict__ for issue in warnings]
    return payload
