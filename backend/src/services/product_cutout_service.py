import os
import uuid
import shutil
import logging
from PIL import Image
from sqlalchemy.orm import Session
from src.db.models import Asset
from src.config import settings

logger = logging.getLogger(__name__)

class ProductCutoutService:
    def __init__(self, db: Session):
        self.db = db

    def generate_cutout(self, source_asset_id: str) -> Asset:
        # Retrieve the source asset
        source_asset = self.db.query(Asset).filter(Asset.id == source_asset_id).first()
        if not source_asset:
            raise ValueError(f"Source asset {source_asset_id} not found")

        # Create destination directory if it doesn't exist
        upload_dir = settings.UPLOAD_DIR
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir, exist_ok=True)

        # Generate a unique filename for the cutout
        filename = f"cutout_{uuid.uuid4().hex}.png"
        file_path = os.path.join(upload_dir, filename)

        # Try to perform background removal using PIL to simulate transparency
        success = False
        try:
            if os.path.exists(source_asset.file_path):
                with Image.open(source_asset.file_path) as img:
                    rgba = img.convert("RGBA")
                    datas = rgba.getdata()
                    new_data = []
                    # Threshold: if pixel is close to white, make it transparent
                    for item in datas:
                        if item[0] > 245 and item[1] > 245 and item[2] > 245:
                            new_data.append((255, 255, 255, 0))
                        else:
                            new_data.append(item)
                    rgba.putdata(new_data)
                    rgba.save(file_path, "PNG")
                    success = True
            else:
                logger.warning(f"Source asset file path does not exist: {source_asset.file_path}")
        except Exception as e:
            logger.error(f"Failed to remove background from {source_asset.file_path}: {e}")

        if not success:
            # Fallback to copy the original file as fallback cutout
            try:
                shutil.copy2(source_asset.file_path, file_path)
            except Exception as e:
                logger.error(f"Fallback copy failed: {e}")
                file_path = source_asset.file_path
                filename = source_asset.filename

        # Save cutout asset
        cutout_asset = Asset(
            project_id=source_asset.project_id,
            source_type="ai_corrected",
            filename=filename,
            file_path=file_path,
            mime_type="image/png",
            file_size=os.path.getsize(file_path) if os.path.exists(file_path) else source_asset.file_size,
            source_asset_id=source_asset.id,
            cutout_status="completed" if success else "failed",
            background_removed=success,
            product_identity_preserved=True
        )
        self.db.add(cutout_asset)
        self.db.commit()
        self.db.refresh(cutout_asset)
        return cutout_asset
