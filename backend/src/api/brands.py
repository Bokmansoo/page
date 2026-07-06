import uuid
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from src.api.auth import get_current_user_and_workspace, require_roles
from src.db.database import get_db
from src.db.models import Brand, AuditLog

router = APIRouter(prefix="/brands", tags=["Brands"])

# =====================================================================
# Request / Response Schemas
# =====================================================================

class BrandCreateSchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    logo_url: Optional[str] = None
    brand_colors: Optional[Dict[str, str]] = Field(default_factory=lambda: {"primary": "#4F46E5", "secondary": "#10B981"})
    font_tone: Optional[str] = "modern"
    default_disclaimer: Optional[str] = None

class BrandUpdateSchema(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    logo_url: Optional[str] = None
    brand_colors: Optional[Dict[str, str]] = None
    font_tone: Optional[str] = None
    default_disclaimer: Optional[str] = None

class BrandResponseSchema(BaseModel):
    id: str
    workspace_id: str
    name: str
    logo_url: Optional[str]
    brand_colors: Optional[Dict[str, str]]
    font_tone: str
    default_disclaimer: Optional[str]

    class Config:
        from_attributes = True

# =====================================================================
# API Endpoints
# =====================================================================

@router.get("", response_model=List[BrandResponseSchema])
def list_brands(
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    return db.query(Brand).filter(Brand.workspace_id == workspace.id).all()


@router.post("", response_model=BrandResponseSchema, status_code=status.HTTP_201_CREATED)
def create_brand(
    payload: BrandCreateSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(require_roles(["owner", "admin"]))
):
    user = auth_ctx["user"]
    workspace = auth_ctx["workspace"]

    brand = Brand(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name=payload.name,
        logo_url=payload.logo_url,
        brand_colors=payload.brand_colors,
        font_tone=payload.font_tone,
        default_disclaimer=payload.default_disclaimer
    )
    db.add(brand)
    db.commit()
    db.refresh(brand)

    # Audit Log
    log = AuditLog(
        workspace_id=workspace.id,
        user_id=user.id,
        action="brand_created",
        entity_type="brand",
        entity_id=brand.id,
        payload={"name": brand.name}
    )
    db.add(log)
    db.commit()

    return brand


@router.patch("/{brand_id}", response_model=BrandResponseSchema)
def update_brand(
    brand_id: str,
    payload: BrandUpdateSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(require_roles(["owner", "admin"]))
):
    user = auth_ctx["user"]
    workspace = auth_ctx["workspace"]

    brand = db.query(Brand).filter(
        Brand.id == brand_id,
        Brand.workspace_id == workspace.id
    ).first()

    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found in this workspace")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(brand, key, value)

    db.commit()
    db.refresh(brand)

    # Audit Log
    log = AuditLog(
        workspace_id=workspace.id,
        user_id=user.id,
        action="brand_updated",
        entity_type="brand",
        entity_id=brand.id,
        payload=update_data
    )
    db.add(log)
    db.commit()

    return brand


@router.delete("/{brand_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_brand(
    brand_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(require_roles(["owner", "admin"]))
):
    user = auth_ctx["user"]
    workspace = auth_ctx["workspace"]

    brand = db.query(Brand).filter(
        Brand.id == brand_id,
        Brand.workspace_id == workspace.id
    ).first()

    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found in this workspace")

    # Prevent deleting the last brand of workspace (each workspace needs at least one brand)
    brand_count = db.query(Brand).filter(Brand.workspace_id == workspace.id).count()
    if brand_count <= 1:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete the last remaining brand of the workspace."
        )

    db.delete(brand)
    
    # Audit Log
    log = AuditLog(
        workspace_id=workspace.id,
        user_id=user.id,
        action="brand_deleted",
        entity_type="brand",
        entity_id=brand_id,
        payload={"brand_id": brand_id}
    )
    db.add(log)
    db.commit()

    return
