from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.db.models import PageSection, ProductFact, ProductPage


LAYOUT_BY_SECTION: dict[str, str] = {
    "comparison": "comparison_cards",
    "detail_1": "benefit_cards",
    "guarantee": "spec_table",
    "hero": "hero_overlay",
}


class BackfillReport(BaseModel):
    project_id: str
    updated: int


def build_grounded_html_payload(section: PageSection, db: Session) -> dict[str, Any]:
    """Build an HTML visual payload using confirmed facts only."""
    layout = LAYOUT_BY_SECTION.get(section.section_type, "image_text")

    confirmed_facts = (
        db.query(ProductFact)
        .filter(
            ProductFact.project_id == section.page.project_id,
            ProductFact.verification_status == "confirmed",
        )
        .all()
    )

    if layout in ("comparison_cards", "benefit_cards"):
        cards = []
        for fact in confirmed_facts:
            cards.append(
                {
                    "title": fact.fact_text[:40],
                    "body": fact.source_text[:80] if fact.source_text else fact.fact_text[:80],
                    "tone": "positive",
                    "verification_status": "confirmed",
                }
            )
        if not cards:
            cards = [
                {
                    "title": section.title or section.section_type,
                    "body": section.body_copy or "",
                    "tone": "muted",
                    "verification_status": "needs_review",
                }
            ]
        return {
            "layout_variant": layout,
            "cards": cards,
        }

    if layout == "spec_table":
        rows = []
        for fact in confirmed_facts:
            rows.append(
                {
                    "label": fact.fact_text[:30],
                    "value": fact.source_text[:50] if fact.source_text else fact.fact_text[:50],
                    "verification_status": "confirmed",
                }
            )
        if not rows:
            rows = [
                {
                    "label": section.title or section.section_type,
                    "value": section.body_copy or "",
                    "verification_status": "needs_review",
                }
            ]
        return {
            "layout_variant": layout,
            "table_rows": rows,
        }

    return {"layout_variant": layout}


def _is_payload_complete(section: PageSection) -> bool:
    """Check if the visual payload has all required fields for its kind."""
    from src.services.page_visual_contract import validate_visual
    visual = {
        "visual_kind": section.visual_kind,
        "visual_payload": section.visual_payload or {},
        "image_asset_id": section.image_asset_id,
    }
    return len(validate_visual(visual)) == 0


def backfill_page_visuals(db: Session, project_id: str) -> BackfillReport:
    """Idempotently backfill visual_kind and visual_payload for legacy PageSection rows.

    Fills both missing visual_kind AND incomplete visual_payload (cards, rows, etc.).
    """
    page = db.query(ProductPage).filter(ProductPage.project_id == project_id).first()
    if not page:
        return BackfillReport(project_id=project_id, updated=0)

    updated = 0
    for section in page.sections:
        if section.visual_kind and _is_payload_complete(section):
            continue  # already fully backfilled

        if section.image_asset_id:
            section.visual_kind = "image"
            section.visual_payload = {
                "layout_variant": "hero_overlay" if section.section_type == "hero" else "image_text"
            }
        else:
            section.visual_kind = "html_graphic"
            section.visual_payload = build_grounded_html_payload(section, db)

        updated += 1

    db.commit()
    return BackfillReport(project_id=project_id, updated=updated)
