from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Any


@dataclass
class CommerceVisualCut:
    section_id: str
    section_type: str
    layout_type: str
    visual_role: str
    headline: str
    subcopy: str
    supporting_text: str | None
    image_asset_id: str | None
    background_style: str
    emphasis_level: int = 1


def _sentence_split(text: str) -> list[str]:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?。！？])\s+|(?<=다\.)\s+", normalized)
    return [part.strip() for part in parts if part.strip()]


def build_commerce_visual_cuts(
    page: dict[str, Any] | Any,
    assets: list[dict[str, Any]],
    project: dict[str, Any] | Any
) -> list[CommerceVisualCut]:
    """Convert page sections into advertising cuts with compressed copy rules."""
    sections = []
    if isinstance(page, dict):
        sections = page.get("sections") or []
    else:
        # SQLAlchemy object
        sections = page.sections

    selected_bg = "cooling-blue"
    if isinstance(project, dict):
        selected_bg = project.get("selected_background") or "cooling-blue"
    else:
        selected_bg = getattr(project, "selected_background", "cooling-blue") or "cooling-blue"

    # Layout type map
    LAYOUT_MAP = {
        "header": "hero_visual",
        "problem_statement": "problem_visual",
        "main_claim": "main_claim_visual",
        "main_claim_support": "proof_visual",
        "benefit_list": "benefit_visual",
        "product_information": "spec_visual",
        "summary_claim": "summary_visual"
    }

    # Visual role map
    ROLE_MAP = {
        "header": "representative_product",
        "problem_statement": "problem_scene",
        "main_claim": "representative_product",
        "main_claim_support": "benefit_visual",
        "benefit_list": "detail_closeup",
        "product_information": "cutout_product",
        "summary_claim": "cta_visual",
        "features": "detail_closeup",
        "specifications": "cutout_product",
        "faq": "faq_graphic",
        "comparison": "comparison_graphic",
        "badges": "badge_set",
        "thumbnail": "thumbnail"
    }

    cuts = []
    for idx, sec in enumerate(sections):
        # Extract fields depending on dict vs SQLAlchemy object
        if isinstance(sec, dict):
            sec_id = sec.get("id") or f"sec-{idx}"
            sec_type = sec.get("section_type") or "unknown"
            title = sec.get("title") or ""
            body_copy = sec.get("body_copy") or sec.get("body") or ""
            image_asset_id = sec.get("image_asset_id")
        else:
            sec_id = getattr(sec, "id", f"sec-{idx}")
            sec_type = getattr(sec, "section_type", "unknown")
            title = getattr(sec, "title", "") or ""
            body_copy = getattr(sec, "body_copy", "") or getattr(sec, "body", "") or ""
            image_asset_id = getattr(sec, "image_asset_id", None)

        layout_type = LAYOUT_MAP.get(sec_type, "benefit_visual")
        visual_role = ROLE_MAP.get(sec_type, "lifestyle_scene")

        # Copy compression rules
        headline = title.strip()
        if len(headline) > 36:
            headline = headline[:35] + "…"

        sentences = _sentence_split(body_copy)
        
        # Subcopy & Supporting text distribution
        subcopy = ""
        supporting_text = None

        if len(sentences) == 1:
            subcopy = sentences[0]
        elif len(sentences) >= 2:
            subcopy = sentences[0]
            supporting_text = " ".join(sentences[1:])
        else:
            subcopy = body_copy

        # Enforce character limits on subcopy (max 90)
        if len(subcopy) > 90:
            subcopy = subcopy[:89] + "…"
        if supporting_text and len(supporting_text) > 120:
            supporting_text = supporting_text[:119] + "…"

        # If it's a spec table, we preserve the full block as body or subcopy without strict cut restriction
        if sec_type == "product_information":
            subcopy = body_copy

        cuts.append(CommerceVisualCut(
            section_id=str(sec_id),
            section_type=sec_type,
            layout_type=layout_type,
            visual_role=visual_role,
            headline=headline,
            subcopy=subcopy,
            supporting_text=supporting_text,
            image_asset_id=image_asset_id,
            background_style=selected_bg,
            emphasis_level=2 if idx == 0 or sec_type in {"header", "main_claim"} else 1
        ))

    return cuts
