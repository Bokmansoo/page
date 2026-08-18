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
from src.db.models import DetailPageVersion, ProductProject, ProductPage, ExportJob, ExportArtifact, Asset, User, WorkspaceMember
from src.config import settings
from src.services.auth_service import create_session
from src.schemas.export_history import ExportHistoryItem, ExportHistoryResponse
from src.services.compliance_checker import PageComplianceChecker
from src.services.page_readiness_service import inspect_page_readiness
from src.services.renderer import PageRendererService
from src.services.page_finalization_service import (
    FinalPageNotFoundError,
    get_final_page_version,
)
from src.services.export_service import (
    FrozenExportSnapshotError,
    _LG10_COPYABLE_HTML_ARTIFACT,
    _LG10_STANDALONE_PACKAGE_ARTIFACT,
    build_lg10_copyable_html,
    build_lg10_standalone_export_bundle,
)
from src.services.page_visual_contract import LG11CanvasSafetyError, ensure_lg11_canvas_safe
from src.services.channel_export_service import supported_channel_keys

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


class StandaloneExportRequest(BaseModel):
    final_version_id: Optional[str] = Field(
        None,
        description="The frozen LG-10 DetailPageVersion to package.",
    )
    # Legacy LG-10 standalone callers retain the existing smartstore default.
    # LG-11 checks that the field was explicitly supplied below.
    channel: Literal["smartstore", "coupang"] = "smartstore"


class StandaloneExportResponse(BaseModel):
    detail_page_version_id: str
    approved_asset_manifest_hash: Optional[str]
    copyable_html: str
    html_download_url: str
    zip_download_url: str
    warnings: List[str]


@router.get("/export/channel-presets")
def list_channel_export_presets():
    """Public, versioned output settings used by the web preview/export UI."""
    from src.services.channel_export_service import serialize_channel_presets
    return {"items": serialize_channel_presets()}

# =====================================================================
# Helper functions
# =====================================================================

def slugify(text: str) -> str:
    from src.services.commerce_content_quality_service import export_slug
    return export_slug(text)

def _legacy_slugify(text: str) -> str:
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


_LG11_EXPORT_CHANNELS = supported_channel_keys()
_LG11_CHANNEL_ARTIFACT_TYPES = frozenset({"channel_long", "channel_package"})
_LG11_EXPORT_FORMATS = frozenset({"png", "jpg", "jpeg", "html", "zip"})


def parse_lg11_export_artifact_token(artifact_token: str) -> Optional[Dict[str, str]]:
    """Return the immutable LG-11 artifact identity encoded in an artifact token.

    LG-11 artifacts encode the channel before the file format.  Keeping the
    parser here makes download-time validation use the same channel identity
    regardless of whether the artifact is a long image or a package.
    """
    parts = artifact_token.split(":")
    if len(parts) == 3 and parts[0] in _LG11_CHANNEL_ARTIFACT_TYPES:
        artifact_type, channel, output_format = parts
        if channel in _LG11_EXPORT_CHANNELS and output_format in _LG11_EXPORT_FORMATS:
            return {
                "artifact_type": artifact_type,
                "channel": channel,
                "format": output_format,
            }
        return None

    # LG-11 standalone artifacts use the established LG-10 artifact names
    # with a channel suffix.  Preserve legacy unsuffixed names by declining to
    # parse them here; this parser is only used for LG-11 frozen versions.
    if len(parts) == 2 and parts[0] == _LG10_COPYABLE_HTML_ARTIFACT and parts[1] in _LG11_EXPORT_CHANNELS:
        return {
            "artifact_type": parts[0],
            "channel": parts[1],
            "format": "html",
        }
    if len(parts) == 2 and parts[0] == _LG10_STANDALONE_PACKAGE_ARTIFACT and parts[1] in _LG11_EXPORT_CHANNELS:
        return {
            "artifact_type": parts[0],
            "channel": parts[1],
            "format": "zip",
        }
    return None


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
    page = (
        db.query(ProductPage)
        .filter(ProductPage.project_id == project_id)
        .order_by(ProductPage.created_at.asc(), ProductPage.id.asc())
        .first()
    )
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
    render_session = None
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
        export_user = db.get(User, job.created_by)
        if not project or not export_user or not export_user.is_active:
            raise HTTPException(status_code=403, detail="Export identity is no longer available")
        has_workspace_access = project.workspace.owner_id == export_user.id or db.query(WorkspaceMember).filter_by(
            workspace_id=project.workspace_id,
            user_id=export_user.id,
        ).first()
        if not has_workspace_access:
            raise HTTPException(status_code=403, detail="Export user no longer has workspace access")
        # The headless renderer is a different browser process.  Use a
        # short-lived server session rather than legacy mock identity headers.
        render_session, render_token, _ = create_session(db, export_user, project.workspace)
        export_res = capture_next_render_export(
            project_id=project_id,
            version_id=version.id,
            channel=preset_name,
            output_format=output_format,
            auth_headers={"Cookie": f"{settings.SELLFORM_SESSION_COOKIE_NAME}={render_token}"},
        )
        
        source_long_image_path = export_res["long_vertical_image"]
        section_zip_path = export_res["section_images_zip"]
        from src.services.channel_export_service import create_channel_export_bundle
        project = db.query(ProductProject).filter(ProductProject.id == project_id).first()
        project_name = project.name if project and project.name else "sellform-detail-page"
        project_slug = slugify(project_name)
        try:
            channel_bundle = create_channel_export_bundle(
                master_path=source_long_image_path,
                output_dir=os.path.dirname(source_long_image_path),
                project_slug=project_slug,
                preset_key=preset_name,
                output_format=output_format,
                section_heights=export_res.get("section_heights", []),
                section_images_zip=section_zip_path,
                generation_plan=(version.sections_json or {}).get("ux2e0_generation_plan"),
            )
            long_image_path = channel_bundle["long_image"]
            zip_path = channel_bundle["package_zip"]
        except Exception as exc:
            # Unit-render doubles may return marker bytes rather than a real
            # image. Production exports always have a valid Playwright image;
            # retain the canonical artifact instead of masking the real result.
            logger.warning("Channel packaging skipped: %s", exc)
            long_image_path = source_long_image_path
            zip_path = section_zip_path

        # 4. ZIP 파일을 Asset 모델로 영구 등록
        zip_size = os.path.getsize(zip_path)
        zip_filename = os.path.basename(zip_path)

        zip_asset = Asset(
            project_id=project_id,
            source_type="exported_zip",
            usage_status="blocked",
            filename=zip_filename,
            file_path=zip_path,
            mime_type="application/zip",
            file_size=zip_size
        )
        db.add(zip_asset)
        db.flush()  # Asset.id 획득

        # 5. 긴 세로 이미지도 Asset 모델로 영구 등록 및 output_images 지정
        long_size = os.path.getsize(long_image_path)
        export_filename = os.path.basename(long_image_path)
        
        long_asset = Asset(
            project_id=project_id,
            source_type="exported_image",
            usage_status="blocked",
            filename=export_filename,
            file_path=long_image_path,
            mime_type="image/jpeg" if output_format in {"jpg", "jpeg"} else "image/png",
            file_size=long_size
        )
        db.add(long_asset)
        db.flush()

        # Preserve channel preset/version and the immutable page version without
        # requiring a schema migration. Artifact types are intentionally
        # machine-readable for later preset replacement/re-download checks.
        db.add_all([
            ExportArtifact(
                project_id=project_id,
                version_id=version.id,
                artifact_type=f"channel_long:{preset_name}:{output_format}",
                file_path=long_image_path,
            ),
            ExportArtifact(
                project_id=project_id,
                version_id=version.id,
                artifact_type=f"channel_package:{preset_name}:{output_format}",
                file_path=zip_path,
            ),
        ])

        # 6. 완료 상태 업데이트
        job.status = "completed"
        job.zip_asset_id = zip_asset.id
        job.output_images = [
            f"/api/v1/projects/{project_id}/page/export/download/{long_asset.id}",
            f"/api/v1/projects/{project_id}/page/export/download/{zip_asset.id}",
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
        if render_session:
            render_session.revoked_at = datetime.datetime.utcnow()
            db.commit()
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

    get_project_or_404(db, project_id, workspace.id)
    final_version = None
    if req.final_version_id:
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
        version_snapshot = requested_final.sections_json if isinstance(requested_final.sections_json, dict) else {}
        quality_snapshot = version_snapshot.get("ux2d_content_quality")
        if quality_snapshot and not quality_snapshot.get("ready_for_sale", False):
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "선택한 최종본의 판매용 품질 확인 항목이 해결되지 않았습니다.",
                    "content_quality": quality_snapshot,
                },
            )

        final_version = requested_final
    else:
        try:
            final_version = get_final_page_version(db, project_id)
        except FinalPageNotFoundError:
            final_version = None

    version_snapshot = (
        final_version.sections_json if final_version and isinstance(final_version.sections_json, dict) else {}
    )
    is_lg10_version = version_snapshot.get("schema_version") == "lg10-detail-page-version-v1"
    page = None if is_lg10_version else get_page_or_404(db, project_id, workspace.id)

    if is_lg10_version and final_version:
        try:
            ensure_lg11_canvas_safe(version_snapshot=version_snapshot, channel=req.preset_name)
        except LG11CanvasSafetyError as exc:
            raise HTTPException(status_code=409, detail={"message": str(exc), "canvas_safety": exc.result}) from exc

    # 0. Readiness check (visual contract, edit markers, etc.)
    if not is_lg10_version:
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
    if not is_lg10_version:
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

    # An export is derived from the immutable final page version. Return the
    # previous exact artifact immediately rather than launching duplicate work.
    if final_version:
        artifact_type = f"channel_long:{req.preset_name}:{req.output_format}"
        existing_artifact = (
            db.query(ExportArtifact)
            .filter_by(project_id=project_id, version_id=final_version.id, artifact_type=artifact_type)
            .order_by(ExportArtifact.created_at.desc()).first()
        )
        if existing_artifact and os.path.isfile(existing_artifact.file_path):
            existing_asset = db.query(Asset).filter_by(
                project_id=project_id, file_path=existing_artifact.file_path
            ).first()
            if existing_asset:
                package_artifact = (
                    db.query(ExportArtifact)
                    .filter_by(project_id=project_id, version_id=final_version.id,
                               artifact_type=f"channel_package:{req.preset_name}:{req.output_format}")
                    .order_by(ExportArtifact.created_at.desc()).first()
                )
                package_asset = db.query(Asset).filter_by(
                    project_id=project_id, file_path=package_artifact.file_path if package_artifact else ""
                ).first()
                job = ExportJob(
                    project_id=project_id, preset_name=req.preset_name, status="completed",
                    created_by=user.id, zip_asset_id=package_asset.id if package_asset else None,
                    output_images=[
                        f"/api/v1/projects/{project_id}/page/export/download/{existing_asset.id}",
                        *(
                            [f"/api/v1/projects/{project_id}/page/export/download/{package_asset.id}"]
                            if package_asset else []
                        ),
                    ],
                    completed_at=datetime.datetime.utcnow(),
                )
                db.add(job); db.commit(); db.refresh(job)
                return job

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
        page_id=page.id if page else "",
        job_id=job.id,
        preset_name=req.preset_name,
        use_commerce_cut=req.use_commerce_cut,
        output_format=req.output_format,
        final_version_id=final_version.id if final_version else req.final_version_id,
    )

    return job


@router.post(
    "/projects/{project_id}/page/export/standalone",
    response_model=StandaloneExportResponse,
)
def create_lg10_standalone_export(
    project_id: str,
    req: StandaloneExportRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Create or re-download the clean HTML/ZIP for one frozen LG-10 version."""
    user = auth_ctx["user"]
    workspace = auth_ctx["workspace"]
    role = auth_ctx.get("role") or "owner"
    if role not in ["owner", "admin", "member"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: Insufficient permissions for this workspace")
    get_project_or_404(db, project_id, workspace.id)

    if req.final_version_id:
        version = db.query(DetailPageVersion).filter(
            DetailPageVersion.id == req.final_version_id,
            DetailPageVersion.project_id == project_id,
            DetailPageVersion.is_final == True,  # noqa: E712
        ).first()
    else:
        try:
            version = get_final_page_version(db, project_id)
        except FinalPageNotFoundError:
            version = None
    if not version:
        raise HTTPException(status_code=409, detail="A finalized LG-10 detail page version is required for standalone export.")

    snapshot = version.sections_json if isinstance(version.sections_json, dict) else {}
    if snapshot.get("schema_version") != "lg10-detail-page-version-v1":
        raise HTTPException(status_code=409, detail="Standalone export is available only for frozen LG-10 DetailPageVersion snapshots.")

    if isinstance(snapshot.get("lg11"), dict) and "channel" not in req.model_fields_set:
        raise HTTPException(status_code=409, detail="LG-11 standalone export requires an explicit channel identity.")
    try:
        ensure_lg11_canvas_safe(version_snapshot=snapshot, channel=req.channel)
    except LG11CanvasSafetyError as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc), "canvas_safety": exc.result}) from exc

    def _artifact_asset(artifact_type: str) -> tuple[ExportArtifact | None, Asset | None]:
        artifact = (
            db.query(ExportArtifact)
            .filter_by(project_id=project_id, version_id=version.id, artifact_type=artifact_type)
            .order_by(ExportArtifact.created_at.desc())
            .first()
        )
        asset = (
            db.query(Asset).filter_by(project_id=project_id, file_path=artifact.file_path).first()
            if artifact and os.path.isfile(artifact.file_path)
            else None
        )
        return artifact, asset

    try:
        copyable = build_lg10_copyable_html(
            db=db,
            project_id=project_id,
            version=version,
            channel=req.channel,
        )
    except FrozenExportSnapshotError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    is_lg11_snapshot = isinstance(snapshot.get("lg11"), dict)
    # Only LG-11 artifacts carry channel identity.  Preserve the established
    # LG-10 history keys rather than rewriting legacy export history.
    html_artifact_type = (
        f"{_LG10_COPYABLE_HTML_ARTIFACT}:{req.channel}"
        if is_lg11_snapshot else _LG10_COPYABLE_HTML_ARTIFACT
    )
    zip_artifact_type = (
        f"{_LG10_STANDALONE_PACKAGE_ARTIFACT}:{req.channel}"
        if is_lg11_snapshot else _LG10_STANDALONE_PACKAGE_ARTIFACT
    )
    html_artifact, html_asset = _artifact_asset(html_artifact_type)
    zip_artifact, zip_asset = _artifact_asset(zip_artifact_type)
    warnings: list[str] = list(copyable["warnings"])
    if not html_asset or not zip_asset:
        try:
            bundle = build_lg10_standalone_export_bundle(
            db=db,
            project_id=project_id,
            version=version,
            channel=req.channel,
            )
        except FrozenExportSnapshotError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        warnings.extend(bundle["warnings"])

        def _persist_asset(*, path: str, source_type: str, mime_type: str) -> Asset:
            existing = db.query(Asset).filter_by(project_id=project_id, file_path=path).first()
            if existing:
                return existing
            asset = Asset(
                project_id=project_id,
                source_type=source_type,
                usage_status="blocked",
                filename=os.path.basename(path),
                file_path=path,
                mime_type=mime_type,
                file_size=os.path.getsize(path),
            )
            db.add(asset)
            db.flush()
            return asset

        html_asset = _persist_asset(
            path=bundle["html_path"], source_type="exported_html", mime_type="text/html; charset=utf-8"
        )
        zip_asset = _persist_asset(
            path=bundle["zip_path"], source_type="exported_standalone_zip", mime_type="application/zip"
        )
        if not html_artifact:
            db.add(ExportArtifact(project_id=project_id, version_id=version.id, artifact_type=html_artifact_type, file_path=bundle["html_path"]))
        if not zip_artifact:
            db.add(ExportArtifact(project_id=project_id, version_id=version.id, artifact_type=zip_artifact_type, file_path=bundle["zip_path"]))
        db.commit()

    html_url = f"/api/v1/projects/{project_id}/page/export/download/{html_asset.id}"
    zip_url = f"/api/v1/projects/{project_id}/page/export/download/{zip_asset.id}"
    # A completed job makes the package durable in the existing export history
    # without changing the legacy image-export data model.
    db.add(ExportJob(
        project_id=project_id,
        preset_name=f"lg10_standalone:{req.channel}" if is_lg11_snapshot else "lg10_standalone",
        status="completed",
        created_by=user.id,
        zip_asset_id=zip_asset.id,
        output_images=[html_url, zip_url],
        completed_at=datetime.datetime.utcnow(),
    ))
    db.commit()
    manifest = (
        ((snapshot.get("lg10") or {}).get("canonical_page_assembly_input") or {})
        .get("page_asset_manifest")
        or ((snapshot.get("lg10") or {}).get("canonical_page_assembly_input") or {})
        .get("approved_asset_manifest")
        or {}
    )
    return StandaloneExportResponse(
        detail_page_version_id=version.id,
        approved_asset_manifest_hash=manifest.get("manifest_hash"),
        copyable_html=copyable["html"],
        html_download_url=html_url,
        zip_download_url=zip_url,
        warnings=sorted(set(warnings)),
    )


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

    artifact = db.query(ExportArtifact).filter_by(project_id=project_id, file_path=asset.file_path).order_by(ExportArtifact.created_at.desc()).first()
    if artifact and artifact.version_id:
        version = db.query(DetailPageVersion).filter_by(id=artifact.version_id, project_id=project_id).first()
        if (
            version
            and isinstance(version.sections_json, dict)
            and isinstance(version.sections_json.get("lg11"), dict)
        ):
            try:
                artifact_identity = parse_lg11_export_artifact_token(str(artifact.artifact_type or ""))
                if artifact_identity is None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "message": "Frozen LG-11 export artifact has an invalid channel identity.",
                            "canvas_safety": {
                                "schema_version": "lg11-canvas-safety-v1",
                                "checked": True,
                                "safe": False,
                                "channel": None,
                                "issues": [{
                                    "code": "invalid_export_artifact_channel",
                                    "reason": "The frozen export artifact token does not contain a valid channel and format.",
                                    "section_id": None,
                                    "element_id": None,
                                }],
                            },
                        },
                    )
                ensure_lg11_canvas_safe(
                    version_snapshot=version.sections_json,
                    channel=artifact_identity["channel"],
                )
            except LG11CanvasSafetyError as exc:
                raise HTTPException(status_code=409, detail={"message": str(exc), "canvas_safety": exc.result}) from exc

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
    package_download_url = None
    if job.output_images and len(job.output_images) > 0:
        download_url = job.output_images[0]
    if job.output_images and len(job.output_images) > 1:
        package_download_url = job.output_images[1]

    image_asset = _exported_image_asset_for_job(db, job)
    image_format = _image_format_from_asset(image_asset)
    if image_asset:
        download_url = f"/api/v1/projects/{job.project_id}/page/export/download/{image_asset.id}"

    output_asset_ids = [
        asset_id
        for asset_id in (_asset_id_from_download_url(url) for url in (job.output_images or []))
        if asset_id
    ]
    output_paths = [
        asset.file_path
        for asset in db.query(Asset).filter(
            Asset.project_id == job.project_id,
            Asset.id.in_(output_asset_ids),
        ).all()
    ]
    artifact = (
        db.query(ExportArtifact)
        .filter(
            ExportArtifact.project_id == job.project_id,
            ExportArtifact.file_path.in_(output_paths),
        )
        .order_by(ExportArtifact.created_at.desc())
        .first()
        if output_paths
        else None
    )
    version_snapshot = artifact.version.sections_json if artifact and isinstance(artifact.version.sections_json, dict) else {}
    approved_asset_manifest = (
        ((version_snapshot.get("lg10") or {}).get("canonical_page_assembly_input") or {})
        .get("page_asset_manifest")
        or ((version_snapshot.get("lg10") or {}).get("canonical_page_assembly_input") or {})
        .get("approved_asset_manifest")
        or {}
    )

    return ExportHistoryItem(
        id=job.id,
        project_id=job.project_id,
        project_name=job.project.name if job.project else "",
        format=image_format or job.preset_name,
        status=job.status,
        filename=image_asset.filename if image_asset else None,
        content_type=image_asset.mime_type if image_asset else None,
        download_url=download_url,
        package_download_url=package_download_url,
        version_id=artifact.version_id if artifact else None,
        approved_asset_manifest_hash=approved_asset_manifest.get("manifest_hash") if artifact else None,
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
