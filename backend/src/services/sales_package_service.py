import hashlib
import json
import os
from sqlalchemy.orm import Session
from src.db.models import ProductProject, ProductPage, ExportJob
from src.services.detail_page_package_service import DetailPagePackageService
from src.services.page_asset_policy import get_page_eligible_assets
from src.api.figma_plugin import build_plugin_snapshot


MARKETPLACE_REQUIRED_FIELDS = [
    "title",
    "category",
    "representative_image",
    "detail_page_artifact",
    "price",
    "delivery",
    "returns",
]


def build_sales_package_hash(marketplace_package: dict) -> str:
    payload = json.dumps(
        marketplace_package,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SalesPackageService:
    @staticmethod
    def get_sales_package(project_id: str, db: Session) -> dict:
        # 1. Detail Page Package 획득 (없는 경우 생성되도록 처리)
        detail_pkg = DetailPagePackageService.get_or_create_detail_page_package(project_id, db)
        
        project = db.query(ProductProject).filter(ProductProject.id == project_id).first()
        if not project:
            return {}
            
        page = db.query(ProductPage).filter(ProductPage.project_id == project_id).first()
        
        # 2. long_png
        # ExportJob에서 completed 상태인 최신 긴 세로 이미지를 가져온다.
        latest_job = db.query(ExportJob).filter(
            ExportJob.project_id == project_id,
            ExportJob.status == "completed"
        ).order_by(ExportJob.completed_at.desc()).first()
        
        long_png_path = None
        long_png_url = None
        if latest_job and latest_job.output_images:
            long_png_url = latest_job.output_images[0]
            filename = long_png_url.split("/")[-1]
            long_png_path = os.path.join(os.getcwd(), "uploads", "exports", filename)
        
        # 3. editable_web_page
        editable_web_page_url = f"/workspace/projects/{project_id}/page-editor"
        
        # 4. figma_payload
        figma_payload = {}
        figma_asset_map = {}
        if page:
            try:
                figma_payload, figma_asset_map = build_plugin_snapshot(project, page, db)
            except Exception:
                pass
                
        # 5. marketplace_package
        intake = project.intake_snapshot if isinstance(project.intake_snapshot, dict) else {}
        
        eligible_assets = get_page_eligible_assets(db, project_id)

        rep_image_url = None
        if intake.get("image_url"):
            rep_image_url = intake.get("image_url")
        else:
            first_asset = eligible_assets[0] if eligible_assets else None
            if first_asset:
                rep_image_url = f"/uploads/{first_asset.filename}"
                
        marketplace_package = {
            "title": intake.get("marketplace_title") or intake.get("title") or project.name,
            "tags": intake.get("tags", [project.category] if project.category else []),
            "category": project.category or intake.get("category"),
            "representative_image": rep_image_url,
            "detail_page_artifact": long_png_url,
            "price": intake.get("price"),
            "delivery": intake.get("delivery"),
            "returns": intake.get("returns"),
            "seo_metadata": {
                "title": f"{project.name} - 구매하기",
                "description": detail_pkg.marketplace_copy.get("description", ""),
                "keywords": ",".join(intake.get("tags", [project.category] if project.category else []))
            }
        }
        missing_fields = [
            field
            for field in MARKETPLACE_REQUIRED_FIELDS
            if not marketplace_package.get(field)
        ]
        package_hash = build_sales_package_hash(marketplace_package)
        approval = intake.get("marketplace_approval") if isinstance(intake.get("marketplace_approval"), dict) else {}
        marketplace_readiness = {
            "ready": not missing_fields,
            "missing_fields": missing_fields,
            "package_hash": package_hash,
            "approved": approval.get("package_hash") == package_hash,
            "approved_at": approval.get("approved_at") if approval.get("package_hash") == package_hash else None,
        }
        
        # 6. copy_sheet
        copy_sheet = [
            {
                "id": sec.get("id"),
                "section_type": sec.get("section_type"),
                "title": sec.get("title"),
                "body_copy": sec.get("body_copy")
            }
            for sec in detail_pkg.copy_sections
        ]
        
        # 7. visual_assets
        visual_assets = [
            {
                "id": a.id,
                "filename": a.filename,
                "file_path": a.file_path,
                "mime_type": a.mime_type,
                "source_type": a.source_type
            }
            for a in eligible_assets
        ]
        
        return {
            "long_png": {
                "file_path": long_png_path,
                "url": long_png_url
            },
            "editable_web_page": {
                "url": editable_web_page_url
            },
            "figma_payload": {
                "payload": figma_payload,
                "asset_map": figma_asset_map
            },
            "marketplace_package": marketplace_package,
            "marketplace_readiness": marketplace_readiness,
            "copy_sheet": copy_sheet,
            "visual_assets": visual_assets
        }
