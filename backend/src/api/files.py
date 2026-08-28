import hashlib
import os
import re
import uuid
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from src.api.auth import get_current_user_and_workspace
from src.config import settings
from src.db.database import get_db
from src.db.models import ProductProject, ProductPage, PageSection, Asset, AuditLog
from src.services.validation import ALLOWED_EXTENSIONS, REVIEW_DOCUMENT_EXTENSIONS, validate_file_upload
from src.services.commerce_policy import initial_asset_usage_status
from src.services.channel_export_service import image_sha256
from src.services.quality_promotion_service import (
    QualityPromotionGateError,
    require_current_quality_export_artifact,
)

router = APIRouter(prefix="/files", tags=["files"])


class AssetResponseSchema(BaseModel):
    id: str
    project_id: str
    source_type: str
    usage_status: str
    filename: str
    mime_type: str
    file_size: int
    intake_order: Optional[int] = None
    source_asset_id: Optional[str] = None
    cutout_status: Optional[str] = None
    background_removed: bool = False
    product_identity_preserved: bool = True
    asset_role: str = "unknown"
    role_confidence: float = 0.0
    role_source: str = "auto"
    quality_status: str = "warning"
    identity_status: str = "needs_review"
    width: Optional[int] = None
    height: Optional[int] = None
    image_format: Optional[str] = None
    quality_warnings: list[str] = []
    safe_crop_status: str = "needs_review"
    is_representative: bool = False
    representative_source: str = "auto"
    classification_version: int = 0
    content_hash: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class AssetUsageStatusUpdateSchema(BaseModel):
    """Seller review result for an asset's final-page eligibility."""

    usage_status: Literal["reference_only", "seller_owned", "blocked"]


@router.post("/upload", response_model=AssetResponseSchema, status_code=status.HTTP_201_CREATED)
async def upload_file(
    project_id: str = Form(...),
    # An API client which omits this field must not silently mark a supplier
    # capture as seller-owned.  The intake UI asks the seller to opt in to a
    # final-use right explicitly.
    source_type: Literal["self_shot", "uploaded", "sourced"] = Form("sourced"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    user = auth_ctx["user"]
    workspace = auth_ctx["workspace"]

    # 1. Verify project exists in workspace
    project = db.query(ProductProject).filter(
        ProductProject.id == project_id,
        ProductProject.workspace_id == workspace.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 2. Read contents to get size and perform validation
    content = await file.read()
    file_size = len(content)
    # Reset read pointer
    await file.seek(0)

    # Perform validation (extension, size limits)
    # Supplier/reference collection may contain review documents. They remain
    # reference-only assets and are parsed only by the LG-7 review pipeline;
    # seller-owned product inputs continue to accept images only.
    allowed_extensions = (
        ALLOWED_EXTENSIONS | REVIEW_DOCUMENT_EXTENSIONS
        if source_type == "sourced"
        else ALLOWED_EXTENSIONS
    )
    validate_file_upload(file, file_size, allowed_extensions=allowed_extensions)

    # 3. Create destination directory if it doesn't exist
    upload_dir = settings.UPLOAD_DIR
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir, exist_ok=True)

    # 4. Generate a unique safe filename
    filename = file.filename or "unnamed"
    file_ext = os.path.splitext(filename)[1]
    safe_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = os.path.join(upload_dir, safe_filename)

    # 5. Save the file to disk
    with open(file_path, "wb") as f:
        f.write(content)

    # 6. Create Asset and Audit Log
    asset = Asset(
        project_id=project_id,
        source_type=source_type,
        usage_status=initial_asset_usage_status(source_type),
        filename=filename,
        file_path=file_path,
        mime_type=file.content_type or "application/octet-stream",
        file_size=file_size,
        content_hash=hashlib.sha256(content).hexdigest(),
    )
    db.add(asset)
    db.flush()
    if asset.mime_type.startswith("image/"):
        from src.services.asset_understanding_service import run_asset_inspection
        from src.services.image_asset_inspector import refresh_representative_product_asset
        from src.services.local_image_upscale import create_auto_upscale_preview

        run_asset_inspection(asset, db)
        # Preserve the original as the automatic representative.  The local
        # enlargement is only a seller-reviewable candidate, never a silent
        # HERO assignment.
        refresh_representative_product_asset(project_id, db)
        upscale_preview = create_auto_upscale_preview(asset, db)
    else:
        upscale_preview = None
    db.commit()
    db.refresh(asset)

    log = AuditLog(
        workspace_id=workspace.id,
        user_id=user.id,
        action="file_uploaded",
        entity_type="asset",
        entity_id=asset.id,
        payload={"filename": filename, "file_size": file_size, "project_id": project_id}
    )
    db.add(log)
    if upscale_preview:
        db.add(
            AuditLog(
                workspace_id=workspace.id,
                user_id=user.id,
                action="asset_local_upscale_auto_suggested",
                entity_type="asset",
                entity_id=upscale_preview.id,
                payload={"source_asset_id": asset.id, "trigger": "LOW_RESOLUTION"},
            )
        )
    db.commit()

    return asset


def _workspace_asset_or_404(asset_id: str, workspace_id: str, db: Session) -> Asset:
    asset = (
        db.query(Asset)
        .join(ProductProject, ProductProject.id == Asset.project_id)
        .filter(Asset.id == asset_id, ProductProject.workspace_id == workspace_id)
        .first()
    )
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


@router.patch("/assets/{asset_id}/usage-status", response_model=AssetResponseSchema)
def update_asset_usage_status(
    asset_id: str,
    payload: AssetUsageStatusUpdateSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Mark a supplier capture as reference-only or approve seller ownership.

    AI-generated and derived-graphic values are set by their own pipelines;
    a seller cannot relabel a supplier capture as AI generated through this
    endpoint.
    """
    asset = _workspace_asset_or_404(asset_id, auth_ctx["workspace"].id, db)
    asset.usage_status = payload.usage_status
    from src.services.storyboard_service import mark_storyboard_assets_stale
    project = db.query(ProductProject).filter(ProductProject.id == asset.project_id).first()
    if project:
        mark_storyboard_assets_stale(project, [asset.id])
    db.add(
        AuditLog(
            workspace_id=auth_ctx["workspace"].id,
            user_id=auth_ctx["user"].id,
            action="asset_usage_status_updated",
            entity_type="asset",
            entity_id=asset.id,
            payload={"usage_status": payload.usage_status},
        )
    )
    db.commit()
    db.refresh(asset)
    return asset


@router.post("/assets/{asset_id}/upscale", response_model=AssetResponseSchema, status_code=status.HTTP_201_CREATED)
def create_upscaled_asset(
    asset_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Create an identity-safe local enlargement while retaining the source."""
    source = _workspace_asset_or_404(asset_id, auth_ctx["workspace"].id, db)
    from src.services.local_image_upscale import ImageUpscaleError, create_local_upscaled_asset

    try:
        enhanced = create_local_upscaled_asset(source, db)
    except ImageUpscaleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    db.add(
        AuditLog(
            workspace_id=auth_ctx["workspace"].id,
            user_id=auth_ctx["user"].id,
            action="asset_local_upscale_created",
            entity_type="asset",
            entity_id=enhanced.id,
            payload={"source_asset_id": source.id, "width": enhanced.width, "height": enhanced.height},
        )
    )
    db.commit()
    db.refresh(enhanced)
    return enhanced


@router.post("/assets/{asset_id}/upscale/apply", response_model=AssetResponseSchema)
def apply_upscaled_asset(
    asset_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Confirm an enlarged asset and replace related low-resolution page uses."""
    enhanced = _workspace_asset_or_404(asset_id, auth_ctx["workspace"].id, db)
    if enhanced.source_type != "local_upscaled" or not enhanced.source_asset_id:
        raise HTTPException(status_code=422, detail="This asset is not a local upscale preview")
    if "LOW_RESOLUTION" in (enhanced.quality_warnings or []):
        raise HTTPException(status_code=422, detail="Enhanced image still does not meet the resolution target")

    project_assets = db.query(Asset).filter(Asset.project_id == enhanced.project_id).all()
    source = next((item for item in project_assets if item.id == enhanced.source_asset_id), None)
    lineage_root_id = source.source_asset_id if source and source.source_asset_id else enhanced.source_asset_id
    related_ids = {
        item.id
        for item in project_assets
        if item.id in {enhanced.source_asset_id, lineage_root_id}
        or item.source_asset_id in {enhanced.source_asset_id, lineage_root_id}
    }

    source_was_representative = bool(source and source.is_representative)
    if source_was_representative:
        for item in project_assets:
            if item.id in related_ids or item.id == enhanced.id:
                item.is_representative = item.id == enhanced.id
                item.representative_source = "manual" if item.id == enhanced.id else "auto"
    # A feature/detail photo must not silently become the representative
    # product photo merely because it was enlarged.
    if source:
        enhanced.asset_role = source.asset_role
        enhanced.role_confidence = source.role_confidence
        enhanced.role_source = source.role_source
        enhanced.identity_status = source.identity_status

    page = db.query(ProductPage).filter(ProductPage.project_id == enhanced.project_id).first()
    if page:
        for section in page.sections:
            if section.image_asset_id not in related_ids:
                continue
            # Upscaling replaces only the linked file. The seller's current
            # layout, crop/fit, background and copy placement stay unchanged.
            section.image_asset_id = enhanced.id

    db.add(
        AuditLog(
            workspace_id=auth_ctx["workspace"].id,
            user_id=auth_ctx["user"].id,
            action="asset_local_upscale_applied",
            entity_type="asset",
            entity_id=enhanced.id,
            payload={
                "source_asset_id": enhanced.source_asset_id,
                "replaced_asset_ids": sorted(related_ids),
                "layout_preserved": True,
            },
        )
    )
    db.commit()
    db.refresh(enhanced)
    return enhanced


@router.get("/assets/{asset_id}")
def get_asset_file(
    asset_id: str,
    expected_content_hash: Optional[str] = None,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    if asset_id.startswith("mock-") or asset_id.startswith("candidate-") or asset_id in {"asset-selected", "asset-default"}:
        from fastapi.responses import Response
        # 1x1 transparent PNG
        dummy_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        return Response(content=dummy_png, media_type="image/png")

    workspace = auth_ctx["workspace"]
    asset = (
        db.query(Asset)
        .join(ProductProject, ProductProject.id == Asset.project_id)
        .filter(Asset.id == asset_id, ProductProject.workspace_id == workspace.id)
        .first()
    )
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")


    file_path = asset.file_path
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Asset file not found")

    # Generic retrieval continues to serve ordinary seller assets after the
    # workspace check above.  A persisted LG-12 export record is different:
    # it is final output and must use the exact same current-page/promotion
    # authority as the protected export-download endpoint.
    try:
        require_current_quality_export_artifact(
            db,
            workspace_id=workspace.id,
            project_id=asset.project_id,
            file_path=file_path,
        )
    except QualityPromotionGateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "quality_gate_blocked", "message": str(exc)},
        ) from exc

    # LG-10 immutable previews/export renders pin a final asset hash in their
    # DetailPageVersion.  Legacy callers omit this optional query parameter
    # and retain the existing file-serving behavior.
    if expected_content_hash is not None:
        if not re.fullmatch(r"[0-9a-f]{64}", expected_content_hash):
            raise HTTPException(status_code=400, detail="Expected asset content hash must be a lowercase SHA-256 hex value")
        if image_sha256(file_path) != expected_content_hash:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "asset_snapshot_hash_mismatch",
                    "message": "Asset bytes no longer match the finalized detail page version.",
                },
            )

    return FileResponse(
        file_path,
        media_type=asset.mime_type,
        filename=asset.filename,
    )
