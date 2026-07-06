import base64
import json
import os
from sqlalchemy.orm import Session
from src.config import settings
from src.db.models import Asset


class PackageTooLarge(Exception):
    pass


class FigmaPluginPackageService:
    def __init__(self, db: Session):
        self.db = db
        self.max_bytes = settings.SELLFORM_FIGMA_PLUGIN_PACKAGE_MAX_BYTES

    def build_package(self, payload: dict, asset_map: dict) -> dict:
        embedded_assets = []
        total_bytes = 0

        for asset_ref, asset_id in asset_map.items():
            asset = self.db.query(Asset).filter(Asset.id == asset_id).first()
            if not asset or not os.path.exists(asset.file_path):
                continue

            file_size = os.path.getsize(asset.file_path)
            total_bytes += file_size

            if total_bytes > self.max_bytes:
                raise PackageTooLarge("Export package size exceeds the limit.")

            with open(asset.file_path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode("utf-8")

            embedded_assets.append({
                "asset_ref": asset_ref,
                "mime_type": asset.mime_type or "image/png",
                "base64": b64_data
            })

        package = {
            "schema_version": "1.0",
            "payload": payload,
            "embedded_assets": embedded_assets
        }
        encoded_size = len(
            json.dumps(package, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        if encoded_size > self.max_bytes:
            raise PackageTooLarge("Export package size exceeds the limit.")
        return package
