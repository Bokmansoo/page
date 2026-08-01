import os
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from src.api.auth import get_current_user_and_workspace
from src.config import settings
from src.db.database import get_db
from src.db.models import ProductProject, ProductPage, PageSection, Asset, AuditLog
from src.services.validation import validate_file_upload

router = APIRouter(prefix="/files", tags=["files"])


class AssetResponseSchema(BaseModel):
    id: str
    project_id: str
    source_type: str
    filename: str
    file_path: str
    mime_type: str
    file_size: int
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
    ocr_text: Optional[str] = None
    safe_crop_status: str = "needs_review"
    is_representative: bool = False
    representative_source: str = "auto"
    classification_version: int = 0

    model_config = ConfigDict(from_attributes=True)


@router.post("/upload", response_model=AssetResponseSchema, status_code=status.HTTP_201_CREATED)
async def upload_file(
    project_id: str = Form(...),
    source_type: str = Form("self_shot"),
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
    validate_file_upload(file, file_size)

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
        filename=filename,
        file_path=file_path,
        mime_type=file.content_type or "application/octet-stream",
        file_size=file_size
    )
    db.add(asset)
    db.flush()
    if asset.mime_type.startswith("image/"):
        from src.services.image_asset_inspector import apply_asset_inspection, refresh_representative_product_asset
        apply_asset_inspection(asset, db)
        refresh_representative_product_asset(project_id, db)
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

    for item in project_assets:
        item.is_representative = item.id == enhanced.id
        item.representative_source = "manual" if item.id == enhanced.id else "auto"
    enhanced.asset_role = "product_main"
    enhanced.role_confidence = 1.0
    enhanced.role_source = "manual"
    enhanced.identity_status = "confirmed"

    page = db.query(ProductPage).filter(ProductPage.project_id == enhanced.project_id).first()
    if page:
        from src.services.hero_composition import build_composed_product_payload

        hero_payload = build_composed_product_payload(enhanced, page.project.selected_style if page.project else None)
        for section in page.sections:
            if section.image_asset_id not in related_ids:
                continue
            section.image_asset_id = enhanced.id
            if section.section_type == "hero" and hero_payload:
                section.visual_kind = "composed_product"
                section.visual_payload = hero_payload

    db.add(
        AuditLog(
            workspace_id=auth_ctx["workspace"].id,
            user_id=auth_ctx["user"].id,
            action="asset_local_upscale_applied",
            entity_type="asset",
            entity_id=enhanced.id,
            payload={"source_asset_id": enhanced.source_asset_id, "replaced_asset_ids": sorted(related_ids)},
        )
    )
    db.commit()
    db.refresh(enhanced)
    return enhanced


@router.get("/assets/{asset_id}")
def get_asset_file(
    asset_id: str,
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

    return FileResponse(
        file_path,
        media_type=asset.mime_type,
        filename=asset.filename,
    )
