import os
import logging
import datetime
from typing import List, Optional, Dict, Any, Literal
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.auth import get_current_user_and_workspace
from src.db.database import get_db, SessionLocal
from src.db.models import ProductProject, ProductPage, ExportJob, Asset, User
from src.schemas.export_history import ExportHistoryItem, ExportHistoryResponse
from src.services.compliance_checker import PageComplianceChecker
from src.services.page_readiness_service import inspect_page_readiness
from src.services.renderer import PageRendererService
from src.services.page_finalization_service import (
    FinalPageNotFoundError,
    get_final_page_version,
)

router = APIRouter(tags=["Exports"])
logger = logging.getLogger(__name__)

# =====================================================================
# Request / Response Schemas
# =====================================================================

class ExportRequest(BaseModel):
    output_format: Literal["png", "jpg", "jpeg"] = "png"
    export_target: Literal["marketplace", "local_download"] = "marketplace"
    final_version_id: Optional[str] = Field(
        None,
        description="Explicit finalized detail page version to export.",
    )
    preset_name: str = Field(..., description="판매처별 프리셋 명칭 (coupang, smartstore)")
    use_commerce_cut: bool = Field(False, description="이미지 중심 커머스 컷 렌더링 사용 여부")

class ComplianceIssueSchema(BaseModel):
    severity: str
    rule: str
    message: str
    section_id: Optional[str]

class ComplianceCheckResponse(BaseModel):
    can_export: bool
    issues: List[ComplianceIssueSchema]

class ExportJobResponse(BaseModel):
    id: str
    project_id: str
    preset_name: str
    status: str
    error_message: Optional[str]
    zip_asset_id: Optional[str]
    output_images: Optional[List[str]]
    created_at: Any
    completed_at: Optional[Any]

    class Config:
        from_attributes = True

# =====================================================================
# Helper functions
# =====================================================================

def slugify(text: str) -> str:
    import re
    text = text.strip()
    text = re.sub(r'\s+', '-', text)
    text = re.sub(r'[^\wㄱ-ㅎㅏ-ㅣ가-힣\-]', '', text)
    text = re.sub(r'\-+', '-', text)
    return text.strip("-").lower()


def _image_format_from_asset(asset: Optional[Asset]) -> Optional[str]:
    if not asset:
        return None
    filename = asset.filename.lower()
    if asset.mime_type == "image/png" or filename.endswith(".png"):
        return "png"
    if asset.mime_type == "image/jpeg" or filename.endswith(".jpg") or filename.endswith(".jpeg"):
        return "jpg"
    return None


def _asset_id_from_download_url(url: str) -> Optional[str]:
    marker = "/page/export/download/"
    if marker not in url:
        return None
    return url.rstrip("/").split(marker, 1)[1].split("?", 1)[0]


def _exported_image_asset_for_job(db: Session, job: ExportJob) -> Optional[Asset]:
    output_asset_ids = [
        asset_id
        for asset_id in (_asset_id_from_download_url(url) for url in (job.output_images or []))
        if asset_id
    ]
    if output_asset_ids:
        asset = (
            db.query(Asset)
            .filter(
                Asset.project_id == job.project_id,
                Asset.source_type == "exported_image",
                Asset.id.in_(output_asset_ids),
            )
            .first()
        )
        if asset:
            return asset

    return (
        db.query(Asset)
        .filter(
            Asset.project_id == job.project_id,
            Asset.source_type == "exported_image",
        )
        .order_by(Asset.created_at.desc())
        .first()
    )


def should_block_export(compliance: Dict[str, Any], export_target: str) -> bool:
    return not compliance["can_export"] and export_target != "local_download"


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
        raise HTTPException(status_code=404, detail="Page draft not found for this project")
    return page

# =====================================================================
# Background Task Definition
# =====================================================================

def run_export_task(
    project_id: str,
    page_id: str,
    job_id: str,
    preset_name: str,
    use_commerce_cut: bool = False,
    output_format: Literal["png", "jpg", "jpeg"] = "png",
    final_version_id: Optional[str] = None,
):
    db = SessionLocal()
    try:
        # 1. 작업 상태를 rendering으로 업데이트
        job = db.query(ExportJob).filter(ExportJob.id == job_id).first()
        if not job:
            return
        job.status = "rendering"
        db.commit()

        # 2. 최종본 지정된 버전 가져오기 (없으면 최신 버전 폴백)
        from src.db.models import DetailPageVersion
        if final_version_id:
            version = db.query(DetailPageVersion).filter(
                DetailPageVersion.id == final_version_id,
                DetailPageVersion.project_id == project_id,
            ).first()
            if not version:
                raise FinalPageNotFoundError(
                    "Final detail page version not found. Please finalize the page before export."
                )
        else:
            version = get_final_page_version(db, project_id)

        # 3. export_service의 run_export 구동
        from src.services.export_service import capture_next_render_export
        project = db.query(ProductProject).filter(ProductProject.id == project_id).first()
        export_res = capture_next_render_export(
            project_id=project_id,
            version_id=version.id,
            output_format=output_format,
            auth_headers={
                "X-Mock-User-Id": job.created_by,
                "X-Mock-Workspace-Id": project.workspace_id if project else "",
            },
        )
        
        long_image_path = export_res["long_vertical_image"]
        zip_path = export_res["section_images_zip"]

        # 4. ZIP 파일을 Asset 모델로 영구 등록
        zip_size = os.path.getsize(zip_path)
        zip_filename = os.path.basename(zip_path)

        zip_asset = Asset(
            project_id=project_id,
            source_type="exported_zip",
            filename=zip_filename,
            file_path=zip_path,
            mime_type="application/zip",
            file_size=zip_size
        )
        db.add(zip_asset)
        db.flush()  # Asset.id 획득

        # 5. 긴 세로 이미지도 Asset 모델로 영구 등록 및 output_images 지정
        long_size = os.path.getsize(long_image_path)
        project_name = project.name if project and project.name else "sellform-detail-page"
        project_slug = slugify(project_name)
        export_filename = f"{project_slug}-상세페이지.{output_format}"
        
        long_asset = Asset(
            project_id=project_id,
            source_type="exported_image",
            filename=export_filename,
            file_path=long_image_path,
            mime_type="image/jpeg" if output_format in {"jpg", "jpeg"} else "image/png",
            file_size=long_size
        )
        db.add(long_asset)
        db.flush()

        # 6. 완료 상태 업데이트
        job.status = "completed"
        job.zip_asset_id = zip_asset.id
        job.output_images = [
            f"/api/v1/projects/{project_id}/page/export/download/{long_asset.id}"
        ]
        job.completed_at = datetime.datetime.utcnow()
        db.commit()

    except Exception as e:
        logger.error(f"Error processing export task in background: {e}", exc_info=True)
        db.rollback()
        job = db.query(ExportJob).filter(ExportJob.id == job_id).first()
        if job:
            job.status = "failed"
            job.error_message = str(e)
            job.completed_at = datetime.datetime.utcnow()
            db.commit()
    finally:
        db.close()

# =====================================================================
# API Routes
# =====================================================================

@router.get("/projects/{project_id}/page/compliance", response_model=ComplianceCheckResponse)
def check_page_compliance(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    page = get_page_or_404(db, project_id, workspace.id)
    result = PageComplianceChecker.inspect_page(db, page)
    return result


@router.post("/projects/{project_id}/page/export", response_model=ExportJobResponse, status_code=202)
def request_page_export(
    project_id: str,
    req: ExportRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    user = auth_ctx["user"]
    workspace = auth_ctx["workspace"]
    role = auth_ctx.get("role") or "owner"

    # 1. Enforce RBAC (viewer cannot export)
    if role not in ["owner", "admin", "member"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Insufficient permissions for this workspace"
        )

    # 2. Check budget and rate limits
    from src.api.auth import check_workspace_limits
    check_workspace_limits(db, workspace.id)

    page = get_page_or_404(db, project_id, workspace.id)
    if req.final_version_id:
        from src.db.models import DetailPageVersion

        requested_final = db.query(DetailPageVersion).filter(
            DetailPageVersion.id == req.final_version_id,
            DetailPageVersion.project_id == project_id,
            DetailPageVersion.is_final == True,  # noqa: E712
        ).first()
        if not requested_final:
            raise HTTPException(
                status_code=409,
                detail="The requested version is not the current finalized page.",
            )

    # 0. Readiness check (visual contract, edit markers, etc.)
    readiness = inspect_page_readiness(page, db)
    if not readiness.ready:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Page is not ready for export. Resolve blockers first.",
                "blockers": [b.model_dump() for b in readiness.blockers],
            },
        )

    # 1. 검수 룰 재확인 (Blocker 있으면 차단)
    compliance = PageComplianceChecker.inspect_page(db, page)
    if should_block_export(compliance, req.export_target):
        blockers = [issue for issue in compliance["issues"] if issue["severity"] == "Blocker"]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Blocker compliance issues must be resolved before export.",
                "issues": blockers
            }
        )

    # 2. ExportJob 생성
    job = ExportJob(
        project_id=project_id,
        preset_name=req.preset_name,
        status="pending",
        created_by=user.id
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # 3. 백그라운드 태스크 등록
    background_tasks.add_task(
        run_export_task,
        project_id=project_id,
        page_id=page.id,
        job_id=job.id,
        preset_name=req.preset_name,
        use_commerce_cut=req.use_commerce_cut,
        output_format=req.output_format,
        final_version_id=req.final_version_id,
    )

    return job


@router.get("/projects/{project_id}/page/export/jobs", response_model=List[ExportJobResponse])
def list_export_jobs(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    get_project_or_404(db, project_id, workspace.id)
    
    return db.query(ExportJob).filter(
        ExportJob.project_id == project_id
    ).order_by(ExportJob.created_at.desc()).all()


@router.get("/projects/{project_id}/page/export/jobs/{job_id}", response_model=ExportJobResponse)
def get_export_job_status(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    get_project_or_404(db, project_id, workspace.id)

    job = db.query(ExportJob).filter(
        ExportJob.id == job_id,
        ExportJob.project_id == project_id
    ).first()
    
    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")
        
    return job


@router.get("/projects/{project_id}/page/export/download/{asset_id}")
def download_export_file(
    project_id: str,
    asset_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    get_project_or_404(db, project_id, workspace.id)

    asset = db.query(Asset).filter(
        Asset.id == asset_id,
        Asset.project_id == project_id
    ).first()

    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    if not os.path.exists(asset.file_path):
        raise HTTPException(status_code=404, detail="File has been deleted or not ready on disk")

    from urllib.parse import quote
    encoded_filename = quote(asset.filename)
    _, ext = os.path.splitext(asset.filename)
    fallback_ascii = f"detail-page{ext}"
    return FileResponse(
        path=asset.file_path,
        media_type=asset.mime_type,
        headers={
            "Content-Disposition": f"attachment; filename=\"{fallback_ascii}\"; filename*=UTF-8''{encoded_filename}",
        },
    )


@router.get("/projects/{project_id}/sales-package")
def get_sales_package(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    get_project_or_404(db, project_id, workspace.id)
    
    from src.services.sales_package_service import SalesPackageService
    return SalesPackageService.get_sales_package(project_id, db)


def _to_export_history_item(job: ExportJob, db: Session) -> ExportHistoryItem:
    download_url = None
    if job.output_images and len(job.output_images) > 0:
        download_url = job.output_images[0]

    image_asset = _exported_image_asset_for_job(db, job)
    image_format = _image_format_from_asset(image_asset)
    if image_asset:
        download_url = f"/api/v1/projects/{job.project_id}/page/export/download/{image_asset.id}"

    return ExportHistoryItem(
        id=job.id,
        project_id=job.project_id,
        project_name=job.project.name if job.project else "",
        format=image_format or job.preset_name,
        status=job.status,
        filename=image_asset.filename if image_asset else None,
        content_type=image_asset.mime_type if image_asset else None,
        download_url=download_url,
        error_message=job.error_message,
        created_at=job.created_at.isoformat() if job.created_at else "",
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )


@router.get("/page/exports", response_model=ExportHistoryResponse)
def list_export_history(
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    workspace = auth_ctx["workspace"]
    jobs = (
        db.query(ExportJob)
        .join(ProductProject, ExportJob.project_id == ProductProject.id)
        .filter(ProductProject.workspace_id == workspace.id)
        .order_by(ExportJob.created_at.desc())
        .limit(100)
        .all()
    )
    return ExportHistoryResponse(items=[_to_export_history_item(job, db) for job in jobs])
