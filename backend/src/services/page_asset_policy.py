from sqlalchemy.orm import Session

from src.db.models import Asset, ImageGenerationJobRecord


ORIGINAL_IMAGE_SOURCE_TYPES = {"uploaded", "sourced", "self_shot"}


def get_page_eligible_assets(
    db: Session,
    project_id: str,
) -> list[Asset]:
    approved_output_ids = {
        output_asset_id
        for (output_asset_id,) in db.query(
            ImageGenerationJobRecord.output_asset_id
        ).filter(
            ImageGenerationJobRecord.project_id == project_id,
            ImageGenerationJobRecord.status == "approved",
            ImageGenerationJobRecord.output_asset_id.isnot(None),
        )
    }
    assets = db.query(Asset).filter(Asset.project_id == project_id).all()
    return [
        asset
        for asset in assets
        if asset.mime_type
        and asset.mime_type.startswith("image/")
        and (
            asset.source_type in ORIGINAL_IMAGE_SOURCE_TYPES
            or asset.id in approved_output_ids
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
