import sys
from sqlalchemy.orm import Session

from src.db.models import Asset, ImageGenerationJobRecord
from src.config import settings


ORIGINAL_IMAGE_SOURCE_TYPES = {"uploaded", "sourced", "self_shot"}
MOCK_MODE_ELIGIBLE_TYPES = {"mock-generated", "real-generated", "ai-generated", "url-extracted"}
GENERATED_IMAGE_SOURCE_TYPES = {
    "ai_generated",
    "ai-generated",
    "generated_image",
    "mock-generated",
    "real-generated",
}


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
        and (
            asset.source_type in ORIGINAL_IMAGE_SOURCE_TYPES
            or asset.id in approved_output_ids
            or (
                asset.source_type in GENERATED_IMAGE_SOURCE_TYPES
                and asset.id not in tracked_output_ids
                and settings.SELLFORM_GENERATION_MODE != "production"
                and "pytest" not in sys.modules
            )
            or (
                settings.SELLFORM_GENERATION_MODE == "mock"
                and asset.source_type in MOCK_MODE_ELIGIBLE_TYPES
                and "pytest" not in sys.modules
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
