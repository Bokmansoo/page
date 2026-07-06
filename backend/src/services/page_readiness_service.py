from __future__ import annotations

from typing import Any, List

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.db.models import ImageGenerationJobRecord, ProductPage, ProductFact, PageSection
from src.services.grounding_validator import detect_claim_risks
from src.services.visual_contract_backfill import backfill_page_visuals
from src.services.page_visual_contract import validate_visual


class ReadinessIssue(BaseModel):
    section_id: str
    code: str
    message: str


class PageReadiness(BaseModel):
    ready: bool
    blockers: List[ReadinessIssue] = Field(default_factory=list)
    warnings: List[ReadinessIssue] = Field(default_factory=list)


def inspect_page_readiness(
    page: ProductPage,
    db: Session | None = None,
) -> PageReadiness:
    """Inspect a ProductPage for export readiness. Returns blockers and warnings."""
    blockers: list[ReadinessIssue] = []
    warnings: list[ReadinessIssue] = []

    # Run backfill if db is available and sections are missing visual contracts
    if db is not None:
        backfill_page_visuals(db, page.project_id)

    project_id = page.project_id
    confirmed_facts: list[str] = []
    if db is not None:
        confirmed_facts = [
            f.fact_text
            for f in db.query(ProductFact).filter(
                ProductFact.project_id == project_id,
                ProductFact.verification_status == "confirmed",
            ).all()
        ]

    all_sections = sorted(page.sections, key=lambda s: s.sort_order)

    for section in all_sections:
        sec_id = section.id

        # --- Visual contract completeness ---
        visual = {
            "visual_kind": section.visual_kind,
            "visual_payload": section.visual_payload or {},
            "image_asset_id": section.image_asset_id,
        }
        visual_issues = validate_visual(visual)
        for issue_code in visual_issues:
            blockers.append(
                ReadinessIssue(
                    section_id=sec_id,
                    code=f"visual_{issue_code}",
                    message=_visual_issue_message(issue_code, section),
                )
            )

        # --- Asset eligibility ---
        if section.visual_kind == "image" and section.image_asset_id:
            if db is not None:
                from src.services.page_asset_policy import get_page_eligible_asset

                generation_job = (
                    db.query(ImageGenerationJobRecord)
                    .filter(
                        ImageGenerationJobRecord.project_id == project_id,
                        ImageGenerationJobRecord.output_asset_id == section.image_asset_id,
                    )
                    .order_by(ImageGenerationJobRecord.updated_at.desc())
                    .first()
                )
                if generation_job and generation_job.status != "approved":
                    blockers.append(
                        ReadinessIssue(
                            section_id=sec_id,
                            code="identity_review_required",
                            message="Generated product image must pass identity review before export",
                        )
                    )
                elif not get_page_eligible_asset(db, project_id, section.image_asset_id):
                    blockers.append(
                        ReadinessIssue(
                            section_id=sec_id,
                            code="asset_not_eligible",
                            message=f"Image asset {section.image_asset_id} is not eligible for this project",
                        )
                    )

        # --- AI edit marker check ---
        combined = f"{section.title or ''} {section.body_copy or ''}"
        if "[AI 수정됨]" in combined:
            blockers.append(
                ReadinessIssue(
                    section_id=sec_id,
                    code="internal_edit_marker",
                    message="Internal edit marker [AI 수정됨] found in section copy. Use the copy rewrite preview API instead.",
                )
            )

        # --- Grounding / claim risks ---
        if combined.strip():
            risks = detect_claim_risks(combined, confirmed_facts)
            for risk in risks:
                warnings.append(
                    ReadinessIssue(
                        section_id=sec_id,
                        code=f"grounding_{risk.risk_type}",
                        message=f"{risk.phrase}: {risk.reason}",
                    )
                )

        # --- Unverified spec exposure ---
        if db is not None:
            unconfirmed = (
                db.query(ProductFact)
                .filter(
                    ProductFact.project_id == project_id,
                    ProductFact.verification_status != "confirmed",
                    ProductFact.verification_status != "rejected",
                )
                .all()
            )
            for fact in unconfirmed:
                if fact.fact_text and fact.fact_text in combined:
                    warnings.append(
                        ReadinessIssue(
                            section_id=sec_id,
                            code="unverified_fact_exposed",
                            message=f"Unverified fact '{fact.fact_text[:50]}' is present in section copy",
                        )
                    )

    return PageReadiness(
        ready=len(blockers) == 0,
        blockers=blockers,
        warnings=warnings,
    )


def _visual_issue_message(code: str, section: PageSection) -> str:
    messages = {
        "image_asset_required": f"Section '{section.section_type}' has visual_kind=image but no image_asset_id",
        "invalid_visual_kind": f"Section '{section.section_type}' has an invalid visual_kind",
        "invalid_html_layout": f"Section '{section.section_type}' has an invalid HTML layout variant",
        "html_cards_required": f"Section '{section.section_type}' is a card layout but has no cards",
        "spec_rows_required": f"Section '{section.section_type}' is a spec table but has no table rows",
    }
    return messages.get(code, f"Visual contract issue: {code}")
