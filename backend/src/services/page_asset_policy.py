from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from src.db.models import Asset, ImageGenerationJobRecord, PageSection, ProductPage
from src.config import settings
from src.services.commerce_policy import is_asset_final_output_eligible


ORIGINAL_IMAGE_SOURCE_TYPES = {
    "uploaded",
    "sourced",
    "self_shot",
    "url-extracted",
    "url-imported",
    "local_upscaled",
}
MOCK_MODE_ELIGIBLE_TYPES = {"mock-generated", "real-generated", "ai-generated", "url-extracted"}
GENERATED_IMAGE_SOURCE_TYPES = {
    "ai_generated",
    "ai-generated",
    "generated_image",
    "mock-generated",
    "real-generated",
}
HERO_AUTO_ASSIGN_BLOCKING_WARNINGS = {
    "LOW_RESOLUTION",
    "EXTREME_ASPECT_RATIO",
    "DUPLICATE_FILE",
    "IMAGE_INTEGRITY_WARNING",
    # A portrait supplier detail image can be technically valid but still crop
    # the product out of a HERO.  It must be reviewed by the seller first.
    "SAFE_CROP_REVIEW_REQUIRED",
}


def has_hero_auto_assign_blocker(asset: Asset | None) -> bool:
    return bool(
        asset
        and HERO_AUTO_ASSIGN_BLOCKING_WARNINGS.intersection(asset.quality_warnings or [])
    )


def clear_unconfirmed_low_quality_hero_assignments(
    db: Session,
    project_id: str,
) -> int:
    """Remove legacy automatic HERO mappings that violate Sprint 2 policy.

    A manually confirmed selection is retained through the visual payload flag
    written by the page editing endpoint.  Everything else is treated as an
    automatic assignment and returned to a visible quality-review state.
    """
    changed = 0
    hero_sections = (
        db.query(PageSection)
        .join(ProductPage, PageSection.page_id == ProductPage.id)
        .filter(
            ProductPage.project_id == project_id,
            PageSection.section_type == "hero",
            PageSection.image_asset_id.isnot(None),
        )
        .all()
    )
    for section in hero_sections:
        asset = (
            db.query(Asset)
            .filter(Asset.id == section.image_asset_id, Asset.project_id == project_id)
            .first()
        )
        payload = dict(section.visual_payload or {})
        if not has_hero_auto_assign_blocker(asset) or payload.get("low_quality_hero_confirmed"):
            continue

        section.image_asset_id = None
        section.visual_kind = "image"
        payload["missing_state"] = "quality_review_required"
        payload["quality_warning_codes"] = sorted(
            HERO_AUTO_ASSIGN_BLOCKING_WARNINGS.intersection(asset.quality_warnings or [])
        )
        section.visual_payload = payload
        flag_modified(section, "visual_payload")
        changed += 1

    if changed:
        db.commit()
    return changed


def get_page_eligible_assets(
    db: Session,
    project_id: str,
) -> list[Asset]:
    generation_records = db.query(
        ImageGenerationJobRecord.output_asset_id,
        ImageGenerationJobRecord.status,
    ).filter(
        ImageGenerationJobRecord.project_id == project_id,
        ImageGenerationJobRecord.output_asset_id.isnot(None),
    ).all()
    approved_output_ids = set()
    tracked_output_ids = set()
    for item in generation_records:
        try:
            if isinstance(item, tuple) and len(item) == 2:
                output_asset_id, status = item
                tracked_output_ids.add(output_asset_id)
                if status == "approved":
                    approved_output_ids.add(output_asset_id)
            elif hasattr(item, "output_asset_id") and hasattr(item, "status"):
                output_asset_id = getattr(item, "output_asset_id")
                status = getattr(item, "status")
                if output_asset_id is not None:
                    tracked_output_ids.add(output_asset_id)
                    if status == "approved":
                        approved_output_ids.add(output_asset_id)
        except Exception:
            pass
    assets = db.query(Asset).filter(Asset.project_id == project_id).all()
    return [
        asset
        for asset in assets
        if asset.mime_type
        and asset.mime_type.startswith("image/")
        and asset.quality_status != "rejected"
        and is_asset_final_output_eligible(asset)
        and (
            asset.source_type in ORIGINAL_IMAGE_SOURCE_TYPES
            or asset.id in approved_output_ids
            or (
                asset.source_type in GENERATED_IMAGE_SOURCE_TYPES
                and asset.id not in tracked_output_ids
                and settings.SELLFORM_GENERATION_MODE != "production"
            )
            or (
                settings.SELLFORM_GENERATION_MODE == "mock"
                and asset.source_type in MOCK_MODE_ELIGIBLE_TYPES
            )
        )
    ]


def get_page_eligible_asset(
    db: Session,
    project_id: str,
    asset_id: str,
) -> Asset | None:
    return next(
        (
            asset
            for asset in get_page_eligible_assets(db, project_id)
            if asset.id == asset_id
        ),
        None,
    )
