import datetime
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import DetailPageVersion, ProductFact, ProductPage
from src.services.page_asset_policy import get_page_eligible_assets


class PageDraftNotFoundError(ValueError):
    pass


class FinalPageNotFoundError(ValueError):
    pass


def build_final_page_snapshot(db: Session, page: ProductPage) -> dict[str, Any]:
    sorted_sections = sorted(page.sections, key=lambda section: section.sort_order)
    facts = db.query(ProductFact).filter(ProductFact.project_id == page.project_id).all()
    assets = get_page_eligible_assets(db, page.project_id)
    eligible_asset_ids = {asset.id for asset in assets}

    return {
        "theme_color": page.theme_color,
        "font_family": page.font_family,
        "style_key": page.project.selected_style if page.project else None,
        "category": page.project.category if page.project else None,
        "sections": [
            {
                "key": section.section_type,
                "section_type": section.section_type,
                "title": section.title,
                "body": section.body_copy,
                "body_copy": section.body_copy,
                "associated_fact_ids": section.associated_fact_ids or [],
                "image_asset_id": (
                    section.image_asset_id
                    if section.image_asset_id in eligible_asset_ids
                    else None
                ),
                "sort_order": section.sort_order,
                "is_visible": section.is_visible,
            }
            for section in sorted_sections
        ],
        "facts_snapshot": [
            {
                "id": fact.id,
                "fact_text": fact.fact_text,
                "source_text": fact.source_text,
                "source_asset_id": fact.source_asset_id,
                "verification_status": fact.verification_status,
                "extraction_source": fact.extraction_source,
                "provider": fact.provider,
                "model_name": fact.model_name,
                "confidence": fact.confidence,
                "needs_review": fact.needs_review,
                "risk_flags": fact.risk_flags,
            }
            for fact in facts
        ],
        "assets_snapshot": [
            {
                "id": asset.id,
                "source_type": asset.source_type,
                "filename": asset.filename,
                "file_path": asset.file_path,
                "mime_type": asset.mime_type,
                "file_size": asset.file_size,
            }
            for asset in assets
        ],
    }


def get_final_page_version(db: Session, project_id: str) -> DetailPageVersion:
    version = (
        db.query(DetailPageVersion)
        .filter(
            DetailPageVersion.project_id == project_id,
            DetailPageVersion.is_final == True,  # noqa: E712
        )
        .order_by(DetailPageVersion.created_at.desc())
        .first()
    )
    if not version:
        raise FinalPageNotFoundError("Final detail page version not found. Please finalize the page before export.")
    return version


def get_page_version_for_export(
    db: Session,
    project_id: str,
    version_id: str,
) -> DetailPageVersion:
    version = (
        db.query(DetailPageVersion)
        .filter(
            DetailPageVersion.id == version_id,
            DetailPageVersion.project_id == project_id,
        )
        .first()
    )
    if not version:
        raise FinalPageNotFoundError("Requested detail page version was not found.")
    return version


def finalize_page(
    db: Session,
    project_id: str,
    name: str | None = None,
) -> DetailPageVersion:
    page = db.query(ProductPage).filter(ProductPage.project_id == project_id).first()
    if not page:
        raise PageDraftNotFoundError("Page draft not found for this project.")

    snapshot = build_final_page_snapshot(db, page)
    style_key = snapshot.get("style_key") or "problem_solution"

    (
        db.query(DetailPageVersion)
        .filter(
            DetailPageVersion.project_id == project_id,
            DetailPageVersion.is_final == True,  # noqa: E712
        )
        .update({"is_final": False})
    )

    version = DetailPageVersion(
        project_id=project_id,
        name=name or f"Final export {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}",
        style_key=style_key,
        sections_json=snapshot,
        is_final=True,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version
