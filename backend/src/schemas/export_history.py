from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class ExportHistoryItem(BaseModel):
    id: str
    project_id: str
    project_name: str
    format: str
    status: str
    filename: Optional[str] = None
    content_type: Optional[str] = None
    download_url: Optional[str] = None
    package_download_url: Optional[str] = None
    version_id: Optional[str] = None
    approved_asset_manifest_hash: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None


class ExportHistoryResponse(BaseModel):
    items: list[ExportHistoryItem]
