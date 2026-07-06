from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


LONG_PROOF_PATTERNS = [
    "KC 인증",
    "상품번호",
    "모델명",
    "제조",
    "수입",
    "품명",
    "인증정보",
]


@dataclass(frozen=True)
class VisualSlot:
    kind: str
    role: str
    fallback_label: str


def _sentence_split(text: str) -> list[str]:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?。！？])\s+|(?<=다\.)\s+", normalized)
    return [part.strip() for part in parts if part.strip()]


def _compress_copy(text: str, max_chars: int = 110) -> str:
    sentences = [
        sentence
        for sentence in _sentence_split(text)
        if not any(pattern in sentence for pattern in LONG_PROOF_PATTERNS)
    ]
    if not sentences:
        sentences = _sentence_split(text)
    copy = " ".join(sentences[:2]).strip()
    if len(copy) <= max_chars:
        return copy
    return copy[: max_chars - 1].rstrip() + "…"


def _extract_spec_rows(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    patterns = [
        ("모델명", r"(?:모델명|품명/모델명)[^A-Za-z0-9가-힣]*(?P<value>[A-Za-z0-9가-힣 /\\-]+)"),
        ("KC 인증", r"(?:KC 인증정보|KC 인증)[^A-Za-z0-9가-힣]*(?P<value>[A-Z0-9\\-]+)"),
        ("상품번호", r"(?:상품번호)[^0-9]*(?P<value>[0-9]+)"),
    ]
    for label, pattern in patterns:
        match = re.search(pattern, text)
        if match:
            rows.append({"label": label, "value": match.group("value").strip()})
    if not rows and text:
        rows.append({"label": "확인 정보", "value": _compress_copy(text, 160)})
    return rows


def _layout_for_key(key: str, index: int) -> str:
    normalized = (key or "").lower()
    if normalized == "product_information":
        return "spec_table"
    if index == 0 or normalized in {"header", "problem_statement"}:
        return "hero"
    if normalized == "benefit_list":
        return "benefit_cards"
    if normalized in {"main_claim_support", "summary_claim"}:
        return "proof_block"
    return "image_text"


def _style_background_tone(selected_style: str | None, section_key: str, index: int) -> str:
    """Return a background_tone string that aligns with the selected style strategy."""
    if selected_style == "lifestyle":
        # Warm, soft tones for lifestyle/emotional direction
        if index == 0 or section_key in {"problem_statement", "summary_claim"}:
            return "warm_neutral"
        if section_key in {"secondary_benefit", "benefit_list"}:
            return "warm_gray"
        return "warm_neutral"
    if selected_style == "spec_focused":
        # Clean, cool tones for spec/information-heavy direction
        if section_key in {"product_information", "main_claim_support"}:
            return "clean_white"
        if section_key in {"benefit_list"}:
            return "ice_gray"
        return "cool_blue"
    # problem_solution (default): cool blue based
    if index == 0 or section_key == "main_claim":
        return "cool_blue"
    if section_key in {"main_claim_support", "product_information"}:
        return "clean_white"
    return "soft_blue"


def _visual_slot_for(layout: str, selected_background: str | None) -> dict[str, str]:
    if selected_background:
        return {
            "kind": "generated_background",
            "role": selected_background,
            "fallback_label": "선택한 배경 비주얼",
        }
    return {
        "kind": "placeholder",
        "role": layout,
        "fallback_label": "image needed",
    }


def build_visual_sections(
    product_name: str,
    category: str,
    sections: list[dict[str, Any]],
    selected_background: str | None = None,
    image_assets: list[dict[str, Any]] | None = None,
    use_commerce_cut: bool = False,
    selected_style: str | None = None,
) -> list[dict[str, Any]]:
    image_assets = image_assets or []
    
    if use_commerce_cut:
        from src.services.commerce_visual_cut_builder import build_commerce_visual_cuts
        cuts = build_commerce_visual_cuts(
            {"sections": sections},
            image_assets,
            {"selected_background": selected_background}
        )
        
        visual_sections: list[dict[str, Any]] = []
        for index, cut in enumerate(cuts):
            matched_asset = next((a for a in image_assets if a.get("id") == cut.image_asset_id), None) if cut.image_asset_id else None
            
            if matched_asset:
                visual_slot = {
                    "kind": "product_image",
                    "role": cut.visual_role,
                    "asset_id": matched_asset.get("id"),
                    "filename": matched_asset.get("filename"),
                    "file_path": matched_asset.get("file_path"),
                    "fallback_label": matched_asset.get("filename") or "상품 이미지"
                }
            else:
                visual_slot = {
                    "kind": "placeholder",
                    "role": cut.visual_role,
                    "fallback_label": "image needed"
                }
                
            visual_section = {
                "key": cut.section_type,
                "layout": cut.layout_type,
                "eyebrow": str(cut.section_type).upper(),
                "headline": cut.headline,
                "subcopy": cut.subcopy,
                "supporting_text": cut.supporting_text,
                "visual_slot": visual_slot,
                "image_asset_id": cut.image_asset_id,
                "background_style": cut.background_style,
                "style": {
                    "style_key": selected_style or "default",
                    "background_tone": _style_background_tone(selected_style, cut.section_type, index),
                },
                "proofs": [],
            }
            
            if cut.layout_type == "spec_visual":
                visual_section["headline"] = "구매 전 확인 정보"
                visual_section["subcopy"] = "구매 전 확인해야 할 핵심 정보를 정리했습니다."
                visual_section["spec_rows"] = _extract_spec_rows(cut.subcopy)
                
            visual_sections.append(visual_section)
            
        return visual_sections

    visual_sections: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        key = section.get("key") or section.get("section_type") or f"section_{index + 1}"
        body = section.get("body") or section.get("body_copy") or ""
        layout = _layout_for_key(key, index)

        # Resolve background_tone based on selected_style
        style_background_tone = _style_background_tone(selected_style, key, index)

        # 이미지 자산 매핑 정보 탐색 (sprint 30)
        image_asset_id = section.get("image_asset_id")
        matched_asset = next((a for a in image_assets if a.get("id") == image_asset_id), None) if image_asset_id else None
        
        if matched_asset:
            visual_slot = {
                "kind": "product_image",
                "role": layout,
                "asset_id": matched_asset.get("id"),
                "filename": matched_asset.get("filename"),
                "file_path": matched_asset.get("file_path"),
                "fallback_label": matched_asset.get("filename") or "상품 이미지"
            }
        else:
            visual_slot = _visual_slot_for(layout, selected_background)

        visual_section = {
            "key": key,
            "layout": layout,
            "eyebrow": str(key).upper(),
            "headline": section.get("title") or product_name,
            "subcopy": _compress_copy(body),
            "visual_slot": visual_slot,
            "proofs": section.get("associated_fact_ids", []),
            "style": {
                "style_key": selected_style or "default",
                "background_tone": style_background_tone,
            },
        }

        if layout == "spec_table":
            visual_section["headline"] = "구매 전 확인 정보"
            visual_section["subcopy"] = "구매 전 확인해야 할 핵심 정보를 정리했습니다."
            visual_section["spec_rows"] = _extract_spec_rows(body)

        visual_sections.append(visual_section)

    return visual_sections
