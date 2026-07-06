from __future__ import annotations

from typing import Any

from src.services.commerce_visual_cut_builder import build_commerce_visual_cuts


SECTION_VISUAL_MAP = {
    "header": {
        "layout_type": "hero_split_visual",
        "image_role": "product_main",
        "fallback_label": "상품 대표 이미지",
        "background_tone": "cool_blue",
        "badges": ["핵심 장점", "생활/리빙", "구매 전 확인"],
    },
    "problem_statement": {
        "layout_type": "problem_visual",
        "image_role": "lifestyle_scene",
        "fallback_label": "고객 불편 장면 이미지",
        "background_tone": "warm_gray",
        "badges": ["불편 상황", "문제 제기"],
    },
    "main_claim": {
        "layout_type": "solution_visual",
        "image_role": "product_main",
        "fallback_label": "상품 해결 장면 이미지",
        "background_tone": "cool_blue",
        "badges": ["해결", "핵심 메시지"],
    },
    "secondary_benefit": {
        "layout_type": "benefit_cards",
        "image_role": "lifestyle_scene",
        "fallback_label": "추가 장점 이미지",
        "background_tone": "soft_blue",
        "badges": ["추가 장점", "사용 경험"],
    },
    "main_claim_support": {
        "layout_type": "proof_visual",
        "image_role": "proof_or_certification",
        "fallback_label": "근거/인증 이미지",
        "background_tone": "clean_white",
        "badges": ["근거", "확인 정보"],
    },
    "benefit_list": {
        "layout_type": "feature_grid",
        "image_role": "detail_closeup",
        "fallback_label": "기능 디테일 이미지",
        "background_tone": "ice_gray",
        "badges": ["기능", "장점"],
    },
    "summary_claim": {
        "layout_type": "lifestyle_visual",
        "image_role": "lifestyle_scene",
        "fallback_label": "사용 상황 이미지",
        "background_tone": "soft_blue",
        "badges": ["사용 상황", "요약"],
    },
    "product_information": {
        "layout_type": "purchase_info",
        "image_role": "package_or_components",
        "fallback_label": "구성품/구매 정보 이미지",
        "background_tone": "clean_white",
        "badges": ["상품 정보", "구매 판단"],
    },
}


def _get_attr(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _visual_slot(image_asset_id: str | None, image_url: str | None, fallback_label: str) -> dict[str, Any]:
    if image_asset_id or image_url:
        return {
            "kind": "image",
            "asset_ref": image_asset_id,
            "image_url": image_url,
            "fallback_label": fallback_label,
        }
    return {
        "kind": "placeholder",
        "asset_ref": None,
        "image_url": None,
        "fallback_label": fallback_label,
    }


STYLE_BACKGROUND_OVERRIDE: dict[str, dict[str, str]] = {
    "lifestyle": {
        "default": "warm_neutral",
        "problem_statement": "warm_neutral",
        "secondary_benefit": "warm_gray",
        "benefit_list": "warm_gray",
        "summary_claim": "warm_neutral",
    },
    "spec_focused": {
        "default": "cool_blue",
        "product_information": "clean_white",
        "main_claim_support": "clean_white",
        "benefit_list": "ice_gray",
    },
    "problem_solution": {},  # use defaults from SECTION_VISUAL_MAP
}


def _apply_style_override(section_type: str, style_key: str, base_tone: str) -> str:
    """Return background_tone adjusted for the selected style strategy."""
    overrides = STYLE_BACKGROUND_OVERRIDE.get(style_key, {})
    if section_type in overrides:
        return overrides[section_type]
    if "default" in overrides:
        return overrides["default"]
    return base_tone


def build_figma_visual_layout(
    project: Any,
    page: Any,
    assets: list[Any],
    image_urls_by_asset_id: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build Figma-specific visual commerce metadata from canonical page sections.

    The existing commerce cut builder is intentionally reused so copy compression
    and canonical section behavior stay aligned with PNG export rendering.
    """
    image_urls_by_asset_id = image_urls_by_asset_id or {}
    commerce_cuts = build_commerce_visual_cuts(page, assets, project)

    selected_style = _get_attr(project, "selected_style", None) or "default"

    visual_cuts: list[dict[str, Any]] = []
    for index, cut in enumerate(commerce_cuts):
        visual_meta = SECTION_VISUAL_MAP.get(cut.section_type, SECTION_VISUAL_MAP["secondary_benefit"])
        image_url = image_urls_by_asset_id.get(cut.image_asset_id or "")
        badges = list(visual_meta["badges"])
        if index == 0 and "첫 화면" not in badges:
            badges.insert(0, "첫 화면")

        base_tone = visual_meta["background_tone"]
        background_tone = _apply_style_override(cut.section_type, selected_style, base_tone)

        visual_cuts.append({
            "section_id": cut.section_id,
            "section_type": cut.section_type,
            "layout_type": visual_meta["layout_type"],
            "headline": cut.headline,
            "subcopy": cut.subcopy,
            "supporting_text": cut.supporting_text,
            "image_role": visual_meta["image_role"],
            "image_asset_ref": cut.image_asset_id,
            "image_url": image_url,
            "visual_slot": _visual_slot(cut.image_asset_id, image_url, visual_meta["fallback_label"]),
            "badges": badges,
            "background_tone": background_tone,
            "emphasis_level": cut.emphasis_level,
        })

    return {
        "layout_version": "commerce_visual_v1",
        "width": 860,
        "category": _get_attr(project, "category", "Unknown") or "Unknown",
        "style_key": selected_style,
        "background_key": _get_attr(project, "selected_background", None) or "cooling-blue",
        "cuts": visual_cuts,
    }
