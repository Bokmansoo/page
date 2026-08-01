"""Identity-safe local image enlargement for low-resolution product photos."""
from __future__ import annotations

import math
import os
import uuid

from PIL import Image, ImageFilter, ImageOps
from sqlalchemy.orm import Session

from src.config import settings
from src.db.models import Asset
from src.services.image_asset_inspector import apply_asset_inspection


TARGET_MIN_EDGE = 1024
MAX_SCALE = 4
MAX_OUTPUT_EDGE = 4096


class ImageUpscaleError(ValueError):
    pass


def _output_dimensions(width: int, height: int) -> tuple[int, int]:
    if min(width, height) >= TARGET_MIN_EDGE:
        raise ImageUpscaleError("Image already meets the high-resolution target")
    scale = min(MAX_SCALE, max(2, math.ceil(TARGET_MIN_EDGE / min(width, height))))
    if max(width, height) * scale > MAX_OUTPUT_EDGE:
        scale = max(1, MAX_OUTPUT_EDGE // max(width, height))
    if scale <= 1:
        raise ImageUpscaleError("Image dimensions are not suitable for safe local enlargement")
    return width * scale, height * scale


def create_local_upscaled_asset(source: Asset, db: Session) -> Asset:
    """Create a separate, non-generative enlarged asset and keep the source."""
    if not source.mime_type or not source.mime_type.startswith("image/"):
        raise ImageUpscaleError("Only image assets can be enhanced")
    if not source.file_path or not os.path.isfile(source.file_path):
        raise ImageUpscaleError("The original image file is not available locally")

    existing = (
        db.query(Asset)
        .filter(
            Asset.project_id == source.project_id,
            Asset.source_asset_id == source.id,
            Asset.source_type == "local_upscaled",
        )
        .order_by(Asset.created_at.desc())
        .first()
    )
    if existing and existing.file_path and os.path.isfile(existing.file_path):
        return existing

    try:
        with Image.open(source.file_path) as opened:
            image = ImageOps.exif_transpose(opened)
            image.load()
            output_size = _output_dimensions(*image.size)
            working = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            enlarged = working.resize(output_size, Image.Resampling.LANCZOS)
            enhanced = enlarged.filter(
                ImageFilter.UnsharpMask(radius=1.2, percent=110, threshold=3)
            )
    except (OSError, ValueError) as exc:
        if isinstance(exc, ImageUpscaleError):
            raise
        raise ImageUpscaleError("The image could not be enhanced") from exc

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    output_path = os.path.join(settings.UPLOAD_DIR, f"{uuid.uuid4()}-upscaled.png")
    try:
        enhanced.save(output_path, format="PNG", optimize=True)
    finally:
        enhanced.close()
        enlarged.close()
        working.close()

    stem = os.path.splitext(source.filename or "product-image")[0]
    asset = Asset(
        project_id=source.project_id,
        source_type="local_upscaled",
        filename=f"{stem}-고화질보정.png",
        file_path=output_path,
        mime_type="image/png",
        file_size=os.path.getsize(output_path),
        source_asset_id=source.id,
        product_identity_preserved=True,
        asset_role=source.asset_role,
        role_confidence=max(float(source.role_confidence or 0), 0.9),
        role_source="manual" if source.asset_role == "product_main" else source.role_source,
        identity_status=source.identity_status,
    )
    db.add(asset)
    db.flush()
    apply_asset_inspection(asset, db)
    db.flush()
    return asset
