import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from src.api.auth import get_current_user_and_workspace
from src.config import settings
from src.db.database import get_db
from src.db.models import ProductProject, Asset, AuditLog
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
