import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.auth import get_current_user_and_workspace
from src.db.database import get_db
from src.db.models import ProductProject, ProductPage, PublishedPage, PageSection, Asset

router = APIRouter(tags=["Publications"])
logger = logging.getLogger(__name__)

# =====================================================================
# Request / Response Schemas
# =====================================================================

class PublishRequest(BaseModel):
    external_store_url: Optional[str] = Field(None, description="외부 판매처 구매 링크 (쿠팡/스마트스토어 등)")
    slug: Optional[str] = Field(None, description="커스텀 경로 슬러그")
    config: Optional[Dict[str, Any]] = Field(None, description="인터랙티브 기능 옵션 설정 (FAQ, Before/After, 비디오 등)")

class UpdatePublicationRequest(BaseModel):
    is_active: Optional[bool] = Field(None, description="공개 활성화 여부")
    external_store_url: Optional[str] = Field(None, description="외부 판매처 구매 링크")
    config: Optional[Dict[str, Any]] = Field(None, description="인터랙티브 기능 옵션 설정")

class PublishedPageResponse(BaseModel):
    id: str
    project_id: str
    page_id: str
    slug: Optional[str]
    is_active: bool
    external_store_url: Optional[str]
    config: Optional[Dict[str, Any]]

    class Config:
        from_attributes = True

# 비인증 일반 사용자용 응답 스키마
class PublicSectionSchema(BaseModel):
    section_type: str
    title: Optional[str]
    body_copy: Optional[str]
    image_asset_id: Optional[str]
    sort_order: int

class PublicPageResponse(BaseModel):
    id: str
    theme_color: str
    font_family: str
    external_store_url: Optional[str]
    config: Optional[Dict[str, Any]]
    sections: List[PublicSectionSchema]
    assets: Dict[str, str]  # id -> 웹 접근가능한 상대 URL 매핑

# =====================================================================
# Helpers
# =====================================================================

def get_project_or_404(db: Session, project_id: str, workspace_id: str) -> ProductProject:
    project = db.query(ProductProject).filter(
        ProductProject.id == project_id,
        ProductProject.workspace_id == workspace_id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Product project not found")
    return project

def get_page_or_404(db: Session, project_id: str, workspace_id: str) -> ProductPage:
    get_project_or_404(db, project_id, workspace_id)
    page = db.query(ProductPage).filter(ProductPage.project_id == project_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="Page draft not found. Create a draft first.")
    return page

# =====================================================================
# API Endpoints
# =====================================================================

@router.post("/projects/{project_id}/publish", response_model=PublishedPageResponse)
def publish_page(
    project_id: str,
    req: PublishRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    page = get_page_or_404(db, project_id, workspace.id)

    # 슬러그 중복 확인
    if req.slug:
        existing_slug = db.query(PublishedPage).filter(
            PublishedPage.slug == req.slug,
            PublishedPage.project_id != project_id
        ).first()
        if existing_slug:
            raise HTTPException(status_code=400, detail="Custom slug is already taken.")

    # 기존 발행 정보 확인
    pub = db.query(PublishedPage).filter(PublishedPage.project_id == project_id).first()

    if pub:
        # 기존 발행 갱신 (재발행)
        pub.page_id = page.id
        if req.external_store_url is not None:
            pub.external_store_url = req.external_store_url
        if req.slug is not None:
            pub.slug = req.slug if req.slug != "" else None
        if req.config is not None:
            pub.config = req.config
        pub.is_active = True
    else:
        # 신규 발행
        pub = PublishedPage(
            project_id=project_id,
            page_id=page.id,
            slug=req.slug if req.slug != "" else None,
            external_store_url=req.external_store_url,
            config=req.config,
            is_active=True
        )
        db.add(pub)

    db.commit()
    db.refresh(pub)
    return pub


@router.get("/projects/{project_id}/publication", response_model=PublishedPageResponse)
def get_publication_info(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    get_project_or_404(db, project_id, workspace.id)

    pub = db.query(PublishedPage).filter(PublishedPage.project_id == project_id).first()
    if not pub:
        raise HTTPException(status_code=404, detail="Page has not been published yet.")
    return pub


@router.patch("/projects/{project_id}/publication", response_model=PublishedPageResponse)
def update_publication_settings(
    project_id: str,
    req: UpdatePublicationRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    get_project_or_404(db, project_id, workspace.id)

    pub = db.query(PublishedPage).filter(PublishedPage.project_id == project_id).first()
    if not pub:
        raise HTTPException(status_code=404, detail="Publication record not found.")

    if req.is_active is not None:
        pub.is_active = req.is_active
    if req.external_store_url is not None:
        pub.external_store_url = req.external_store_url
    if req.config is not None:
        pub.config = req.config

    db.commit()
    db.refresh(pub)
    return pub


# =====================================================================
# PUBLIC API (인증 필요 없음)
# =====================================================================
@router.get("/public/pages/{id_or_slug}", response_model=PublicPageResponse)
def get_public_landing_page(
    id_or_slug: str,
    db: Session = Depends(get_db)
):
    # UUID ID 또는 Slug로 조회
    pub = db.query(PublishedPage).filter(
        (PublishedPage.id == id_or_slug) | (PublishedPage.slug == id_or_slug)
    ).first()

    if not pub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Landing page not found"
        )

    # 비활성화(비공개) 상태인 경우 조회 불가 차단
    if not pub.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="This landing page is currently set to private."
        )

    # 상세페이지 초안 상태 가져오기
    page = db.query(ProductPage).filter(ProductPage.id == pub.page_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="Underlying page details not found")

    # 가시적인 섹션만 필터링하여 sort_order 순으로 노출
    visible_sections = db.query(PageSection).filter(
        PageSection.page_id == page.id,
        PageSection.is_visible == True
    ).order_by(PageSection.sort_order).all()

    sections_res = [
        PublicSectionSchema(
            section_type=sec.section_type,
            title=sec.title,
            body_copy=sec.body_copy,
            image_asset_id=sec.image_asset_id,
            sort_order=sec.sort_order
        )
        for sec in visible_sections
    ]

    # 공개 페이지 이미지 갤러리와 섹션/전후비교에 쓰이는 프로젝트 이미지 에셋 정보 매핑 수집
    project_assets = db.query(Asset).filter(Asset.project_id == pub.project_id).all()
    asset_ids = [asset.id for asset in project_assets]
    asset_ids.extend([sec.image_asset_id for sec in visible_sections if sec.image_asset_id])
    
    # config 내부의 Before/After 이미지 에셋도 함께 수집
    config = pub.config or {}
    before_after = config.get("before_after_slider", {})
    if before_after.get("enabled"):
        if before_after.get("before_image_id"):
            asset_ids.append(before_after.get("before_image_id"))
        if before_after.get("after_image_id"):
            asset_ids.append(before_after.get("after_image_id"))

    assets_map = {}
    unique_asset_ids = list(dict.fromkeys(asset_ids))
    if unique_asset_ids:
        assets = db.query(Asset).filter(Asset.id.in_(unique_asset_ids)).all()
        for asset in assets:
            # /uploads/파일명 형태의 웹 접근 가능 상대 경로 반환
            assets_map[asset.id] = f"/uploads/{asset.filename}"

    return PublicPageResponse(
        id=pub.id,
        theme_color=page.theme_color,
        font_family=page.font_family,
        external_store_url=pub.external_store_url,
        config=pub.config,
        sections=sections_res,
        assets=assets_map
    )
