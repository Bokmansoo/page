# This module uses legacy SQLAlchemy Column declarations whose instance values
# are resolved dynamically at runtime. Pyright otherwise treats them as Column
# objects and reports false positives throughout the API layer.
# pyright: reportArgumentType=false, reportAssignmentType=false, reportReturnType=false, reportGeneralTypeIssues=false, reportCallIssue=false, reportOptionalMemberAccess=false, reportAttributeAccessIssue=false

import logging
import uuid
from datetime import datetime, timezone
import anthropic
from typing import Optional, List, Dict, Any, Literal
from types import SimpleNamespace
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from src.api.auth import get_current_user_and_workspace
from src.config import settings
from src.db.database import get_db
from src.db.models import ProductProject, ProductPage, PageSection, PageVersion, DetailPageVersion, ProductFact, Asset, User, AgentRun, ImageGenerationJobRecord, CommerceStoryBaselineRecord, BrandKitVersion
from src.schemas.planning_draft import PlanningDraftSchema
from src.schemas.api_ready_generation import (
    ApiReadyGenerationPlanSchema,
    GroundedCopyDraftRequestSchema,
    GroundedCopyDraftResponseSchema,
    GroundedCopyDraftDecisionSchema,
    GroundedCopyDraftEstimateSchema,
    GenerationPlanUpdateSchema,
)

from src.services.page_generator import PageGenerationService
from src.services.style_strategy_service import generate_style_candidates, get_category_frame, is_valid_style_candidate_key
from src.services.grounding_validator import detect_claim_risks, map_section_to_facts
from src.services.copy_rewrite_service import CopyRewriteCommand, CopyRewriteService, CopyRewriteResult
from src.services.detail_page_package_service import DetailPagePackageService, DetailPagePackage, AiEditCommandPayload
from src.services.page_readiness_service import PageReadiness, inspect_page_readiness
from src.services.commerce_story_baseline import (
    BaselineProductResponse,
    BaselineRegistrationRequest,
    BaselineRegistrationResponse,
    CommerceStoryBaselineReport,
    EVALUATION_ITEMS,
    get_baseline_product,
    inspect_commerce_story_baseline,
    list_baseline_products,
    serialize_baseline_product,
)
from src.services.page_finalization_service import (
    EditIntentValidationError,
    FinalPageNotFoundError,
    PageDraftNotFoundError,
    finalize_page,
    get_final_page_version,
    get_page_version_for_export,
    preview_lg11_edit_intent,
)
from src.services.page_asset_policy import (
    clear_unconfirmed_low_quality_hero_assignments,
    get_page_eligible_asset,
    get_page_eligible_assets,
)
from src.services.visual_contract_backfill import backfill_page_visuals
from src.services.planning_draft_service import PlanningDraftService
from src.services.commerce_policy import CONFIRMED_FACT_STATUSES, final_spec_is_last, resolved_asset_usage_status
from src.services.storyboard_service import (
    StoryboardValidationError,
    approve_storyboard,
    generate_storyboard,
    record_storyboard_revision,
    restore_storyboard_revision,
    select_recommendation,
    validate_storyboard,
)
from src.services.commerce_renderer_service import build_commerce_artifact


router = APIRouter(tags=["Page Editor"])
logger = logging.getLogger(__name__)

# =====================================================================
# Request / Response Schemas
# =====================================================================

class CreatePageRequest(BaseModel):
    style_preset: Optional[str] = Field("modern", description="스타일 프리셋 (modern, emotional, formal)")
    primary_color: Optional[str] = Field(None, description="테마 주색상")
    narrative_template: Literal["category_default", "problem_solution"] = Field(
        "category_default",
        description="상세페이지 설득 구조 템플릿 (category_default, problem_solution)"
    )


class PlanningDraftApprovalRequest(BaseModel):
    """Permit a text-first page draft while AI scene images are pending."""

    allow_pending_images: bool = False


class SectionUpdateSchema(BaseModel):
    id: str
    title: Optional[str] = None
    body_copy: Optional[str] = None
    image_asset_id: Optional[str] = None
    visual_kind: Optional[Literal["image", "html_graphic", "composed_product"]] = None
    visual_payload: Optional[dict] = None
    sort_order: int
    is_visible: bool

class SectionCreateSchema(BaseModel):
    section_type: str = Field(..., description="섹션 유형(header, features, specifications, faq 등)")
    title: Optional[str] = None
    body_copy: Optional[str] = None
    associated_fact_ids: List[str] = []
    image_asset_id: Optional[str] = None
    visual_kind: Optional[Literal["image", "html_graphic", "composed_product"]] = None
    visual_payload: Optional[dict] = None
    sort_order: Optional[int] = None

class UpdatePageRequest(BaseModel):
    theme_color: Optional[str] = None
    font_family: Optional[str] = None
    sections: List[SectionUpdateSchema]
    confirm_low_quality_hero: bool = False
    # The latest DetailPageVersion id known by the editor.  Omitting this keeps
    # legacy clients working; providing it gives Sprint 6 block edits an
    # optimistic-locking guard instead of silently overwriting another edit.
    expected_version_id: Optional[str] = None
    # UX-2B: an unsupported claim is first returned as a warning. The client
    # must explicitly send this acknowledgement on a second save attempt.
    confirm_unsupported_claims: bool = False


class CommerceRendererArtifactSchema(BaseModel):
    artifact_version: str
    template_key: str
    template_tokens: Dict[str, Any]
    theme_color: str
    font_family: str
    sections: List[Dict[str, Any]]
    renderer_rules: Dict[str, Any]
    artifact_hash: str
    ready: bool
    blockers: List[Dict[str, Any]]
    warnings: List[Dict[str, Any]] = []


class ContentQualityAcknowledgementSchema(BaseModel):
    section_id: str
    code: str
    asset_id: Optional[str] = None

class RegenerateSectionRequest(BaseModel):
    user_instruction: str = Field(..., description="AI에게 내릴 섹션 수정 요구사항")


class StoryboardRecommendationSelectSchema(BaseModel):
    candidate_key: str


class StoryboardRestoreSchema(BaseModel):
    revision: int


class GroundingWarningSchema(BaseModel):
    risk_type: str
    phrase: str
    reason: str
    suggestion: str

class GroundingSummarySchema(BaseModel):
    warning_count: int
    grounded_section_count: int
    used_fact_count: int

class SectionResponseSchema(BaseModel):
    id: str
    section_type: str
    title: Optional[str]
    body_copy: Optional[str]
    associated_fact_ids: Optional[List[str]]
    associated_fact_texts: List[str] = []
    image_asset_id: Optional[str]
    visual_kind: Optional[str] = None
    visual_payload: Optional[dict] = None
    sort_order: int
    is_visible: bool
    warnings: List[str] = []
    grounding_warnings: List[GroundingWarningSchema] = []
    matched_facts: List[str] = []
    image_candidates: List[dict] = []

    # Sprint 78 Section Component Contract
    role: Optional[str] = None
    headline: Optional[str] = None
    body: Optional[str] = None
    evidence_fact_ids: Optional[List[str]] = None
    visual_strategy: Optional[str] = None
    editable: bool = True

    class Config:
        from_attributes = True


class PageResponseSchema(BaseModel):
    id: str
    project_id: str
    theme_color: str
    font_family: str
    sections: List[SectionResponseSchema]
    grounding_summary: Optional[GroundingSummarySchema] = None

    class Config:
        from_attributes = True

class PageVersionResponseSchema(BaseModel):
    id: str
    project_id: str
    name: str
    style_key: str
    is_final: bool
    created_at: Any
    lg11_frozen: bool = False

    class Config:
        from_attributes = True


class PageVersionSnapshotSchema(PageVersionResponseSchema):
    sections_json: Dict[str, Any]


class FinalPageVersionResponseSchema(PageVersionResponseSchema):
    sections_json: Dict[str, Any]


class StyleCandidateResponse(BaseModel):
    key: str
    name: str
    is_ai_recommended: bool
    channel_fit: str
    sales_strategy: str
    design_direction: str
    preview_summary: str
    reason: str


class StyleCandidatesResponse(BaseModel):
    candidates: List[StyleCandidateResponse]
    selected_key: Optional[str] = None
    generation: int = 0


class RegenerateStyleRequest(BaseModel):
    feedback_option: str


class EditIntentPreviewRequest(BaseModel):
    """Read-only LG-11 request normalized against a frozen LG-10 version."""

    scope: Literal["page", "section", "scene", "copy", "style", "fact"]
    target_ids: List[str] = Field(min_length=1)
    operation: str = Field(min_length=1)
    instruction: str = Field(min_length=1)
    preserve_constraints: Dict[str, Any] = Field(default_factory=dict)
    # Direct-editor text changes are deliberately part of the immutable
    # EditIntent.  A later natural-language editor can normalize into this
    # same field map without creating a second version-fork contract.
    copy_changes: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    replacement_asset_id: str | None = None
    seller_attested: bool = False
    # Style edits select only an existing immutable LG-10 direction and an
    # optional, workspace-owned Brand Kit version.  Raw color/font values do
    # not enter the edit contract.
    design_direction: str | None = None
    brand_kit_version_id: str | None = None
    # The Canvas selection is advisory only until it is pinned into the
    # immutable EditIntent preserve constraints below.  It is never resolved
    # from a mutable editor draft during execution.
    selected_section_id: str | None = Field(default=None, max_length=100)
    selected_element_id: str | None = Field(default=None, max_length=160)


class EditRunStartResponse(BaseModel):
    run_id: str
    source_detail_page_version_id: str
    parent_detail_page_version_id: str
    intent_id: str
    state: Dict[str, Any]


# =====================================================================
# Helper for snapshotting page data
# =====================================================================

def create_page_snapshot(page: ProductPage, db: Optional[Session] = None) -> Dict[str, Any]:
    """
    Serialize product page state to a JSON-serializable dictionary.
    """
    sorted_sections = sorted(page.sections, key=lambda section: section.sort_order)

    facts = []
    assets = []
    eligible_asset_ids: set[str] = set()
    if db is not None:
        facts = db.query(ProductFact).filter(ProductFact.project_id == page.project_id).all()
        assets = get_page_eligible_assets(db, page.project_id)
        eligible_asset_ids = {asset.id for asset in assets}

    snapshot = {
        "theme_color": page.theme_color,
        "font_family": page.font_family,
        "style_key": page.project.selected_style if page.project else None,
        "category": page.project.category if page.project else None,
        "sections": [
            {
                "key": sec.section_type,
                "section_type": sec.section_type,
                "title": sec.title,
                "body": sec.body_copy,
                "body_copy": sec.body_copy,
                "associated_fact_ids": sec.associated_fact_ids or [],
                "image_asset_id": (
                    sec.image_asset_id
                    if db is None or sec.image_asset_id in eligible_asset_ids
                    else None
                ),
                "visual_kind": sec.visual_kind,
                "visual_payload": sec.visual_payload or {},
                "facts_stale": sec.facts_stale,
                "sort_order": sec.sort_order,
                "is_visible": sec.is_visible
            }
            for sec in sorted_sections
        ],
        "facts_snapshot": [
            {
                "id": fact.id,
                "fact_text": fact.fact_text,
                "source_text": fact.source_text,
                "source_asset_id": fact.source_asset_id,
                "verification_status": fact.verification_status,
                "extraction_source": fact.extraction_source,
                "provider": fact.provider,
                "model_name": fact.model_name,
                "confidence": fact.confidence,
                "needs_review": fact.needs_review,
                "risk_flags": fact.risk_flags,
                "field_key": fact.field_key,
                "fact_category": fact.fact_category,
                "original_text": fact.original_text,
                "translated_text": fact.translated_text,
                "normalized_value": fact.normalized_value,
                "normalized_unit": fact.normalized_unit,
                "scope": fact.scope,
                "model_option": fact.model_option,
                "extractor_version": fact.extractor_version,
                "conflict_group_key": fact.conflict_group_key,
                "evidence_ids": [item.id for item in fact.evidences],
            }
            for fact in facts
        ],
        "assets_snapshot": [
            {
                "id": asset.id,
                "source_type": asset.source_type,
                "filename": asset.filename,
                "file_path": asset.file_path,
                "mime_type": asset.mime_type,
                "file_size": asset.file_size,
            }
            for asset in assets
        ],
    }
    if db is not None:
        from src.services.commerce_content_quality_service import inspect_content_quality
        from src.services.api_ready_generation_service import (
            generation_rendering_contract,
            get_generation_plan as get_api_ready_generation_plan,
        )
        snapshot["ux2d_content_quality"] = inspect_content_quality(page, db)
        generation_plan = get_api_ready_generation_plan(page.project)
        if generation_plan:
            snapshot["ux2e0_generation_plan"] = generation_plan
            snapshot.setdefault("commerce_renderer", {})["api_generation"] = generation_rendering_contract(generation_plan)
    return snapshot


def get_project_or_404(db: Session, project_id: str, workspace_id: str) -> ProductProject:
    project = db.query(ProductProject).filter(
        ProductProject.id == project_id,
        ProductProject.workspace_id == workspace_id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Product project not found")
    return project


def get_page_or_404(db: Session, project_id: str, workspace_id: str) -> ProductPage:
    project = get_project_or_404(db, project_id, workspace_id)
    # Repair pages created by the old visual-job route. It produced a red/blue
    # mock bitmap in local mode; replace that persisted output with the user's
    # original product photo before a page is displayed or exported.
    from src.services.detail_page_orchestrator import DetailPageOrchestrator
    DetailPageOrchestrator.repair_mock_visual_assets(project, db)
    page = (
        db.query(ProductPage)
        .filter(ProductPage.project_id == project_id)
        .order_by(ProductPage.created_at.asc(), ProductPage.id.asc())
        .first()
    )
    if not page:
        raise HTTPException(status_code=404, detail="Page draft not found for this project")
    return page


def get_visual_ready_page_or_404(db: Session, project_id: str, workspace_id: str) -> ProductPage:
    """Load page after idempotently repairing legacy/incomplete visual contracts."""
    page = get_page_or_404(db, project_id, workspace_id)
    report = backfill_page_visuals(db, project_id)
    if report.updated:
        # Do not call get_page_or_404 a second time here. That helper repairs
        # old mock image jobs and would re-attach the same source product photo
        # after the visual backfill just replaced repeated body photos with
        # fact-grounded HTML graphics.
        db.expire_all()
        page = db.query(ProductPage).filter(ProductPage.project_id == project_id).first()
        if not page:
            raise HTTPException(status_code=404, detail="Page draft not found for this project")
    return page


def get_unconfirmed_warnings(db: Session, project_id: str) -> List[str]:
    unconfirmed_facts = db.query(ProductFact).filter(
        ProductFact.project_id == project_id,
        ProductFact.verification_status.notin_(CONFIRMED_FACT_STATUSES)
    ).all()
    return [f.fact_text for f in unconfirmed_facts]


def format_planning_card_body_copy(card: dict) -> str:
    bullets = [
        str(bullet).strip()
        for bullet in (card.get("bullets") or [])
        if str(bullet).strip()
    ]
    if len(bullets) <= 1:
        return "\n".join(bullets)
    return "\n".join(
        bullet if bullet.startswith(("- ", "* ", "• ")) else f"- {bullet}"
        for bullet in bullets
    )


def _asset_candidate_block_reason(asset: Asset) -> str | None:
    """Explain why a project image cannot be placed in a final page yet."""
    usage_status = resolved_asset_usage_status(asset)
    if usage_status == "reference_only":
        return "공급처·참고 사진입니다. 최종 사용 권한을 확인한 뒤에만 선택할 수 있습니다."
    if usage_status == "blocked":
        return "최종 상세페이지에 사용할 수 없는 사진입니다. 출처와 사용 권한을 확인해 주세요."
    if asset.quality_status == "rejected":
        return "이미지 품질 검토에서 제외된 사진입니다."
    return "최종 출력에 사용할 수 없는 사진입니다."


def _asset_candidate_recommended(section: PageSection, asset: Asset) -> bool:
    """Keep recommendations deterministic while the seller remains in control."""
    role = (asset.asset_role or "unknown").lower()
    section_type = (section.section_type or "").lower()
    preferred_roles = {
        "hero": {"product_main"},
        "feature_1": {"feature", "product_detail", "material_detail"},
        "feature_2": {"feature", "product_detail", "material_detail"},
        "feature_3": {"feature", "product_detail", "material_detail"},
        "usage_guide": {"usage_scene", "feature", "product_detail"},
        "details_components": {"components", "package", "shipping_info", "spec_reference"},
        "product_information": {"spec_reference", "package", "components", "shipping_info"},
    }
    return role in preferred_roles.get(section_type, set()) or (
        section_type == "hero" and bool(asset.is_representative)
    )


def _with_project_asset_candidates(
    candidates: list[dict],
    section: PageSection,
    db: Session,
    project_id: str,
) -> list[dict]:
    """Append project photos when no image-generation job exists.

    UX-2C treats generated-image jobs as optional.  A seller must always be
    able to select a direct upload, while reference-only photos remain visible
    with a clear permission block instead of silently disappearing.
    """
    eligible_ids = {asset.id for asset in get_page_eligible_assets(db, project_id)}
    existing_asset_ids = {
        str(candidate.get("asset_id"))
        for candidate in candidates
        if candidate.get("asset_id")
    }
    project_assets = (
        db.query(Asset)
        .filter(Asset.project_id == project_id, Asset.mime_type.like("image/%"))
        .order_by(Asset.is_representative.desc(), Asset.created_at.asc())
        .all()
    )
    result = list(candidates)
    for asset in project_assets:
        if asset.id in existing_asset_ids:
            continue
        eligible = asset.id in eligible_ids
        result.append(
            {
                "candidate_id": f"asset:{asset.id}",
                "slot_id": section.section_type,
                "asset_id": asset.id,
                "label": asset.filename,
                "source_type": asset.source_type,
                "usage_status": resolved_asset_usage_status(asset),
                "eligible": eligible,
                "block_reason": None if eligible else _asset_candidate_block_reason(asset),
                "asset_role": asset.asset_role,
                "is_recommended": _asset_candidate_recommended(section, asset),
                "recommendation_reason": (
                    f"{asset.asset_role or '미분류'} 역할이 {section.section_type} 섹션과 일치합니다."
                    if _asset_candidate_recommended(section, asset)
                    else None
                ),
                "needs_identity_review": asset.identity_status != "confirmed",
                "status": "available" if eligible else "blocked",
                "quality_warnings": asset.quality_warnings or [],
                "source_asset_id": asset.source_asset_id,
                "cutout_status": asset.cutout_status,
                "background_removed": asset.background_removed,
                "product_identity_preserved": asset.product_identity_preserved,
            }
        )
    return result


def get_image_candidates_for_section(
    section: PageSection,
    db: Session,
    project_id: str,
) -> list:
    job_records = (
        db.query(ImageGenerationJobRecord)
        .filter(
            ImageGenerationJobRecord.project_id == project_id,
            ImageGenerationJobRecord.section_id == section.id,
        )
        .order_by(ImageGenerationJobRecord.updated_at.desc())
        .all()
    )

    if job_records:
        enriched_candidates = []
        for job in job_records:
            output_asset = None
            if job.output_asset_id:
                output_asset = db.query(Asset).filter(Asset.id == job.output_asset_id).first()
            source_asset = None
            if (
                not output_asset
                and job.error_code == "LOW_QUALITY_HERO_SOURCE"
                and job.source_asset_ids
            ):
                source_asset = (
                    db.query(Asset)
                    .filter(
                        Asset.id == job.source_asset_ids[0],
                        Asset.project_id == project_id,
                    )
                    .first()
                )
                # The low-resolution original stays traceable in the job, but
                # an upload-time local upscale preview is the candidate the
                # seller should review and explicitly select for HERO.
                if source_asset:
                    upscale_preview = (
                        db.query(Asset)
                        .filter(
                            Asset.project_id == project_id,
                            Asset.source_type == "local_upscaled",
                            Asset.source_asset_id == source_asset.id,
                            Asset.quality_status != "rejected",
                        )
                        .order_by(Asset.created_at.desc())
                        .first()
                    )
                    if upscale_preview:
                        source_asset = upscale_preview

            if job.output_asset_id:
                label = "\uc0dd\uc131 \uc774\ubbf8\uc9c0"
            elif job.error_code == "REFERENCE_IMAGE_REDESIGN_REQUIRED":
                label = "AI 리디자인 이미지 생성 필요"
            elif job.status == "failed":
                label = "\uc774\ubbf8\uc9c0 \uc0dd\uc131 \uc2e4\ud328"
            else:
                label = "\uc774\ubbf8\uc9c0 \uc0dd\uc131 \ub300\uae30"

            cand_dict = {
                "candidate_id": job.job_id,
                "asset_id": job.output_asset_id or (source_asset.id if source_asset else None),
                "label": label,
                "source_type": "ai_generated",
                "status": (
                    "awaiting_ai_redesign"
                    if job.error_code == "REFERENCE_IMAGE_REDESIGN_REQUIRED"
                    else "quality_review_required" if source_asset else job.status
                ),
                "prompt": job.prompt,
                "error_code": job.error_code,
                "warnings": job.warnings or [],
                "provider": job.provider,
                "model": job.model,
            }
            linked_asset = output_asset or source_asset
            if linked_asset:
                # Existing seller images can fulfill a generation job. The
                # linked Asset is the source of truth for the provenance shown
                # in the candidate card.
                cand_dict["source_type"] = linked_asset.source_type or cand_dict["source_type"]
                if linked_asset.source_type in {
                    "uploaded",
                    "self_shot",
                    "sourced",
                    "url-extracted",
                    "url-imported",
                    "local_upscaled",
                }:
                    cand_dict["label"] = linked_asset.filename
                cand_dict["quality_warnings"] = linked_asset.quality_warnings or []
                cand_dict["source_asset_id"] = linked_asset.source_asset_id
                cand_dict["cutout_status"] = linked_asset.cutout_status
                cand_dict["background_removed"] = linked_asset.background_removed
                cand_dict["product_identity_preserved"] = linked_asset.product_identity_preserved
            enriched_candidates.append(cand_dict)
        return _with_project_asset_candidates(
            enriched_candidates, section, db, project_id
        )
    
    candidates = []
    if job_records:
        candidates = [
            {
                "candidate_id": job.job_id,
                "asset_id": job.output_asset_id,
                "label": "생성 이미지" if job.output_asset_id else "이미지 생성 대기",
                "source_type": "ai_generated",
                "status": job.status,
                "prompt": job.prompt,
            }
            for job in job_records
        ]
    else:
        recent_run = (
            db.query(AgentRun)
            .filter(
                AgentRun.project_id == project_id,
                AgentRun.status == "completed",
            )
            .order_by(AgentRun.completed_at.desc())
            .first()
        )
        if recent_run and recent_run.outputs_json:
            image_generation = recent_run.outputs_json.get("image_generation") or {}
            candidates_by_slot = image_generation.get("candidates") or {}
            slot_id = section.section_type
            if slot_id.startswith("sec-"):
                slot_id = {
                    "sec-1": "hero",
                    "sec-2": "comparison",
                    "sec-3": "detail_1",
                    "sec-4": "detail_2",
                    "sec-5": "guarantee",
                }.get(slot_id, "hero")
            candidates = candidates_by_slot.get(slot_id) or []

    enriched_candidates = []
    for cand in candidates:
        cand_dict = dict(cand)
        asset_id = cand_dict.get("asset_id")
        if asset_id:
            asset = db.query(Asset).filter(Asset.id == asset_id).first()
            if asset:
                cand_dict["source_asset_id"] = asset.source_asset_id
                cand_dict["cutout_status"] = asset.cutout_status
                cand_dict["background_removed"] = asset.background_removed
                cand_dict["product_identity_preserved"] = asset.product_identity_preserved
        enriched_candidates.append(cand_dict)
    return _with_project_asset_candidates(enriched_candidates, section, db, project_id)


def build_section_response(section: PageSection, db: Session) -> SectionResponseSchema:
    project_id = section.page.project_id if section.page else db.query(ProductPage).filter(ProductPage.id == section.page_id).first().project_id
    confirmed_facts = db.query(ProductFact).filter(
        ProductFact.project_id == project_id,
        ProductFact.verification_status.in_(CONFIRMED_FACT_STATUSES)
    ).all()
    facts_list = [f.fact_text for f in confirmed_facts]
    unconfirmed_warnings = get_unconfirmed_warnings(db, project_id)
    
    text = f"{section.title or ''} {section.body_copy or ''}"
    g_warnings = detect_claim_risks(text, facts_list)
    matched_facts = map_section_to_facts(text, facts_list)
    
    candidates_list = get_image_candidates_for_section(section, db, project_id)
    associated_fact_texts = [
        fact.fact_text
        for fact in confirmed_facts
        if fact.id in (section.associated_fact_ids or [])
    ]

    return SectionResponseSchema(
        id=section.id,
        section_type=section.section_type,
        title=section.title,
        body_copy=section.body_copy,
        associated_fact_ids=section.associated_fact_ids,
        associated_fact_texts=associated_fact_texts,
        image_asset_id=section.image_asset_id,
        visual_kind=section.visual_kind or ("image" if section.image_asset_id else None),
        visual_payload=section.visual_payload or {},
        sort_order=section.sort_order,
        is_visible=section.is_visible,
        warnings=unconfirmed_warnings,
        grounding_warnings=[
            GroundingWarningSchema(
                risk_type=w.risk_type,
                phrase=w.phrase,
                reason=w.reason,
                suggestion=w.suggestion
            ) for w in g_warnings
        ],
        matched_facts=matched_facts,
        image_candidates=candidates_list
    )



def build_page_response(page: ProductPage, db: Session) -> PageResponseSchema:
    confirmed_facts = db.query(ProductFact).filter(
        ProductFact.project_id == page.project_id,
        ProductFact.verification_status.in_(CONFIRMED_FACT_STATUSES)
    ).all()
    facts_list = [f.fact_text for f in confirmed_facts]
    unconfirmed_warnings = get_unconfirmed_warnings(db, page.project_id)
    
    sections_res = []
    used_facts = set()
    warning_count = 0
    grounded_section_count = 0

    for section in sorted(page.sections, key=lambda item: item.sort_order):
        text = f"{section.title or ''} {section.body_copy or ''}"
        g_warnings = detect_claim_risks(text, facts_list)
        matched_facts = map_section_to_facts(text, facts_list)
        associated_fact_texts = [
            fact.fact_text
            for fact in confirmed_facts
            if fact.id in (section.associated_fact_ids or [])
        ]

        for fact in matched_facts:
            used_facts.add(fact)
        if matched_facts:
            grounded_section_count += 1
        warning_count += len(g_warnings)

        sections_res.append(SectionResponseSchema(
            id=section.id,
            section_type=section.section_type,
            title=section.title,
            body_copy=section.body_copy,
            associated_fact_ids=section.associated_fact_ids,
            associated_fact_texts=associated_fact_texts,
            image_asset_id=section.image_asset_id,
            visual_kind=section.visual_kind or ("image" if section.image_asset_id else None),
            visual_payload=section.visual_payload or {},
            sort_order=section.sort_order,
            is_visible=section.is_visible,
            warnings=unconfirmed_warnings,
            grounding_warnings=[
                GroundingWarningSchema(
                    risk_type=w.risk_type,
                    phrase=w.phrase,
                    reason=w.reason,
                    suggestion=w.suggestion
                ) for w in g_warnings
            ],
            matched_facts=matched_facts,
            image_candidates=get_image_candidates_for_section(
                section,
                db,
                page.project_id,
            ),
        ))

    return PageResponseSchema(
        id=page.id,
        project_id=page.project_id,
        theme_color=page.theme_color,
        font_family=page.font_family,
        sections=sections_res,
        grounding_summary=GroundingSummarySchema(
            warning_count=warning_count,
            grounded_section_count=grounded_section_count,
            used_fact_count=len(used_facts)
        )
    )



# =====================================================================
# API Endpoints
# =====================================================================

@router.get("/projects/{project_id}/style-candidates", response_model=StyleCandidatesResponse)
def get_style_candidates(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    project = get_project_or_404(db, project_id, workspace.id)

    # Use persisted snapshot if available, otherwise generate fresh candidates
    if isinstance(project.style_candidates_snapshot, list) and project.style_candidates_snapshot:
        candidates_res = [
            StyleCandidateResponse(**c) for c in project.style_candidates_snapshot
        ]
    else:
        confirmed_facts = db.query(ProductFact).filter(
            ProductFact.project_id == project_id,
            ProductFact.verification_status.in_(CONFIRMED_FACT_STATUSES)
        ).all()
        facts = [f.fact_text for f in confirmed_facts]

        candidates = generate_style_candidates(
            category=project.category or "Living",
            product_title=project.name,
            confirmed_facts=facts
        )
        candidates_res = [
            StyleCandidateResponse(
                key=c.key,
                name=c.name,
                is_ai_recommended=c.is_ai_recommended,
                channel_fit=c.channel_fit,
                sales_strategy=c.sales_strategy,
                design_direction=c.design_direction,
                preview_summary=c.preview_summary,
                reason=c.reason
            )
            for c in candidates
        ]
        # Persist initial snapshot
        project.style_candidates_snapshot = [c.model_dump() for c in candidates_res]
        db.commit()

    return StyleCandidatesResponse(
        candidates=candidates_res,
        selected_key=project.selected_style,
        generation=project.style_generation or 0
    )


@router.post("/projects/{project_id}/style-candidates/regenerate", response_model=StyleCandidatesResponse)
def regenerate_style_candidates(
    project_id: str,
    req: RegenerateStyleRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    project = get_project_or_404(db, project_id, workspace.id)

    confirmed_facts = db.query(ProductFact).filter(
        ProductFact.project_id == project_id,
        ProductFact.verification_status.in_(CONFIRMED_FACT_STATUSES)
    ).all()
    facts = [f.fact_text for f in confirmed_facts]

    candidates = generate_style_candidates(
        category=project.category or "Living",
        product_title=project.name,
        confirmed_facts=facts,
        feedback_option=req.feedback_option
    )

    candidates_res = [
        StyleCandidateResponse(
            key=c.key,
            name=c.name,
            is_ai_recommended=c.is_ai_recommended,
            channel_fit=c.channel_fit,
            sales_strategy=c.sales_strategy,
            design_direction=c.design_direction,
            preview_summary=c.preview_summary,
            reason=c.reason
        )
        for c in candidates
    ]

    # Increment generation counter and persist new snapshot.
    # IMPORTANT: selected_style is intentionally NOT overwritten here.
    new_generation = (project.style_generation or 0) + 1
    project.style_generation = new_generation
    project.style_candidates_snapshot = [c.model_dump() for c in candidates_res]
    db.commit()

    return StyleCandidatesResponse(
        candidates=candidates_res,
        selected_key=project.selected_style,
        generation=new_generation
    )


@router.post("/projects/{project_id}/style-candidates/{candidate_key}/select")
def select_style_candidate(
    project_id: str,
    candidate_key: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    project = get_project_or_404(db, project_id, workspace.id)

    if not is_valid_style_candidate_key(candidate_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid style candidate key",
        )

    legacy_keys = {
        "persuasion": "problem_solution",
        "emotional": "lifestyle",
        "information": "spec_focused"
    }
    mapped_key = legacy_keys.get(candidate_key, candidate_key)
    project.selected_style = mapped_key
    db.commit()

    return {"status": "success", "selected_style": mapped_key}


@router.post("/projects/{project_id}/page", response_model=PageResponseSchema, status_code=201)
def create_page_draft(
    project_id: str,
    req: CreatePageRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    # 프로젝트 유무 확인
    workspace = auth_ctx["workspace"]
    project = get_project_or_404(db, project_id, workspace.id)

    # 7단 구조 및 스타일 전략 매핑을 위해 selected_style 사용
    selected_style = project.selected_style or "problem_solution"
    narrative_tmpl = "problem_solution" if selected_style in {"problem_solution", "spec_focused", "lifestyle"} else (req.narrative_template or "category_default")

    # 1. 확정 및 미확정 사실 구분 수집
    confirmed_facts = db.query(ProductFact).filter(
        ProductFact.project_id == project_id,
        ProductFact.verification_status.in_(CONFIRMED_FACT_STATUSES)
    ).all()
    
    unconfirmed_facts = db.query(ProductFact).filter(
        ProductFact.project_id == project_id,
        ProductFact.verification_status.notin_(CONFIRMED_FACT_STATUSES)
    ).all()

    # AI 입력 데이터 준비 (dict 목록)
    facts_data = [
        {"id": f.id, "fact_text": f.fact_text, "source_text": f.source_text}
        for f in confirmed_facts
    ]

    # 2. AI 상세페이지 생성 서비스 호출
    generator = PageGenerationService()
    generated_page = generator.generate_page(
        category=project.category or "Living",
        confirmed_facts=facts_data,
        style_preset=selected_style,
        primary_color=req.primary_color,
        narrative_template=narrative_tmpl,
        sales_strategy=(
            project.intake_snapshot.get("confirmed_sales_strategy")
            if isinstance(project.intake_snapshot, dict)
            else None
        ),
    )


    # 3. 기존 페이지가 존재하면 삭제 처리 (Overwrite 정책)
    existing_page = db.query(ProductPage).filter(ProductPage.project_id == project_id).first()
    if existing_page:
        db.delete(existing_page)
        db.commit()

    # 4. 새 상세페이지 생성
    new_page = ProductPage(
        project_id=project_id,
        theme_color=generated_page.theme_color,
        font_family=generated_page.font_family
    )
    db.add(new_page)
    db.flush()  # new_page.id 획득

    # 5. 새 섹션들 생성 적재
    for idx, sec_schema in enumerate(generated_page.sections):
        new_section = PageSection(
            page_id=new_page.id,
            section_type=sec_schema.section_type,
            title=sec_schema.title,
            body_copy=sec_schema.body_copy,
            associated_fact_ids=sec_schema.associated_fact_ids,
            sort_order=idx,
            is_visible=True
        )
        db.add(new_section)

    db.commit()
    db.refresh(new_page)

    # 5.5 상품 이미지 자동 매핑 연동 (sprint 30)
    try:
        image_assets = get_page_eligible_assets(db, project_id)
        if image_assets:
            sections_data = [{"id": sec.id, "section_type": sec.section_type or ""} for sec in new_page.sections]
            assets_data = [
                {
                    "id": a.id,
                    "filename": a.filename,
                    "mime_type": a.mime_type,
                    "source_type": a.source_type,
                    "asset_role": a.asset_role,
                    "role_confidence": a.role_confidence,
                    "quality_status": a.quality_status,
                    "quality_warnings": a.quality_warnings or [],
                    "content_hash": a.content_hash,
                    "ocr_text": a.ocr_text,
                    "is_representative": a.is_representative,
                }
                for a in image_assets
            ]
            
            from src.services.image_asset_mapper import map_image_assets_to_sections
            assignments = map_image_assets_to_sections(sections_data, assets_data)
            
            sec_map = {sec.id: sec for sec in new_page.sections}
            for assignment in assignments:
                sec = sec_map.get(assignment["section_id"])
                if sec:
                    sec.image_asset_id = assignment["asset_id"]
            db.commit()
            db.refresh(new_page)
    except Exception as e:
        logger.warning(f"상세페이지 초안 생성 후 이미지 자산 자동 매핑 실패: {e}", exc_info=True)

    backfill_page_visuals(db, project_id)
    db.refresh(new_page)

    from src.services.page_version_service import create_page_version
    create_page_version(
        project_id=project_id,
        name="AI 초안 생성",
        sections=create_page_snapshot(new_page, db),
        style_key=selected_style,
        db=db
    )

    return build_page_response(new_page, db)


@router.get("/projects/{project_id}/page", response_model=PageResponseSchema)
def get_page_details(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    page = get_visual_ready_page_or_404(db, project_id, workspace.id)
    if not page:
        raise HTTPException(status_code=404, detail="Page draft not found for this project")

    clear_unconfirmed_low_quality_hero_assignments(db, project_id)
    page = get_visual_ready_page_or_404(db, project_id, workspace.id)
    return build_page_response(page, db)


@router.get("/projects/{project_id}/page/content-quality")
def get_page_content_quality(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    page = get_visual_ready_page_or_404(db, project_id, auth_ctx["workspace"].id)
    from src.services.commerce_content_quality_service import inspect_content_quality
    return inspect_content_quality(page, db)


@router.post("/projects/{project_id}/page/content-quality/acknowledge")
def acknowledge_page_content_quality(
    project_id: str,
    payload: ContentQualityAcknowledgementSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    page = get_visual_ready_page_or_404(db, project_id, auth_ctx["workspace"].id)
    section = next((item for item in page.sections if item.id == payload.section_id), None)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    from src.services.commerce_content_quality_service import inspect_content_quality
    current_quality = inspect_content_quality(page, db)
    acknowledgeable_codes = {
        "duplicate_asset", "duplicate_asset_group", "foreign_text_exposed",
        "phone_number_exposed", "price_exposed", "qr_code_review",
        "market_or_competitor_text", "supplier_text_exposed",
    }
    matching_issue = next(
        (
            issue for issue in current_quality["reviews"]
            if issue["section_id"] == payload.section_id
            and issue["code"] == payload.code
            and issue.get("asset_id") == payload.asset_id
        ),
        None,
    )
    if payload.code not in acknowledgeable_codes or not matching_issue:
        raise HTTPException(status_code=422, detail="This quality item must be corrected rather than acknowledged")
    entries = list((section.visual_payload or {}).get("ux2d_quality_acknowledgements", []))
    marker = {
        "code": payload.code,
        "asset_id": payload.asset_id,
        "acknowledged_by": auth_ctx["user"].id,
        "acknowledged_at": datetime.now(timezone.utc).isoformat(),
    }
    if not any(item.get("code") == marker["code"] and item.get("asset_id") == marker["asset_id"] for item in entries if isinstance(item, dict)):
        entries.append(marker)
    section.visual_payload = {**dict(section.visual_payload or {}), "ux2d_quality_acknowledgements": entries}
    db.commit()
    from src.services.page_version_service import create_page_version
    quality = inspect_content_quality(page, db)
    snapshot = create_page_snapshot(page, db)
    snapshot["ux2d_content_quality"] = quality
    create_page_version(
        project_id=project_id,
        name="판매용 품질 확인",
        sections=snapshot,
        style_key=page.project.selected_style or "problem_solution",
        db=db,
    )
    return quality


@router.get(
    "/projects/{project_id}/page/commerce-artifact",
    response_model=CommerceRendererArtifactSchema,
)
def get_commerce_renderer_artifact(
    project_id: str,
    template_key: Literal["commerce_story", "commerce_story_soft", "commerce_story_bold"] = "commerce_story",
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Return the immutable snapshot consumed by preview and export.

    This is intentionally read-only: page edits continue through PATCH and
    create a normal DetailPageVersion afterwards.  The response gives the UI a
    single contract for export/readiness messages and prevents supplier
    reference files from slipping into an output renderer.
    """
    workspace = auth_ctx["workspace"]
    page = get_visual_ready_page_or_404(db, project_id, workspace.id)
    assets = db.query(Asset).filter(Asset.project_id == project_id).all()
    return build_commerce_artifact(page, assets, template_key=template_key)


@router.get("/projects/{project_id}/page/readiness", response_model=PageReadiness)
def get_page_readiness(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    page = get_visual_ready_page_or_404(db, project_id, workspace.id)
    clear_unconfirmed_low_quality_hero_assignments(db, project_id)
    page = get_visual_ready_page_or_404(db, project_id, workspace.id)
    return inspect_page_readiness(page, db)


@router.get("/commerce-story-baselines", response_model=List[BaselineProductResponse])
def list_commerce_story_baselines(
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """The three fixed Sprint 0 product packs used by later regression checks."""
    workspace = auth_ctx["workspace"]
    registrations = {
        record.baseline_key: record
        for record in db.query(CommerceStoryBaselineRecord).filter(
            CommerceStoryBaselineRecord.workspace_id == workspace.id
        ).all()
    }
    return [
        serialize_baseline_product(product, registrations.get(product.key))
        for product in list_baseline_products()
    ]


@router.put(
    "/commerce-story-baselines/{baseline_key}/registration",
    response_model=BaselineRegistrationResponse,
)
def register_commerce_story_baseline(
    baseline_key: str,
    request: BaselineRegistrationRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Register the seller-approved evidence for a fixed Sprint 0 baseline."""
    baseline = get_baseline_product(baseline_key)
    if not baseline:
        raise HTTPException(status_code=404, detail="Unknown commerce-story baseline")
    workspace = auth_ctx["workspace"]
    user = auth_ctx["user"]
    project = get_project_or_404(db, request.project_id, workspace.id)

    _validate_baseline_asset(
        db,
        request.reference_capture_asset_id,
        project.id,
        field_name="reference_capture_asset_id",
        must_be_jpg=False,
    )
    _validate_baseline_asset(
        db,
        request.baseline_export_asset_id,
        project.id,
        field_name="baseline_export_asset_id",
        must_be_jpg=True,
    )
    invalid_evaluation_keys = set(request.evaluation).difference(EVALUATION_ITEMS)
    if invalid_evaluation_keys:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown evaluation items: {', '.join(sorted(invalid_evaluation_keys))}",
        )

    record = (
        db.query(CommerceStoryBaselineRecord)
        .filter(
            CommerceStoryBaselineRecord.workspace_id == workspace.id,
            CommerceStoryBaselineRecord.baseline_key == baseline.key,
        )
        .first()
    )
    if record is None:
        record = CommerceStoryBaselineRecord(
            workspace_id=workspace.id,
            baseline_key=baseline.key,
            project_id=project.id,
            created_by=user.id,
        )
        db.add(record)
    record.project_id = project.id
    record.reference_capture_asset_id = request.reference_capture_asset_id
    record.baseline_export_asset_id = request.baseline_export_asset_id
    record.evaluation_json = {
        key: bool(request.evaluation.get(key, False))
        for key in EVALUATION_ITEMS
    }
    db.commit()
    db.refresh(record)
    return BaselineRegistrationResponse(
        baseline_key=record.baseline_key,
        project_id=record.project_id,
        reference_capture_asset_id=record.reference_capture_asset_id,
        baseline_export_asset_id=record.baseline_export_asset_id,
        evaluation=record.evaluation_json or {},
    )


@router.get(
    "/projects/{project_id}/commerce-story-baseline",
    response_model=CommerceStoryBaselineReport,
)
def get_commerce_story_baseline(
    project_id: str,
    baseline_key: Optional[str] = None,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Sprint 0 quality report used before moving to the commerce-story sprints."""
    workspace = auth_ctx["workspace"]
    page = get_visual_ready_page_or_404(db, project_id, workspace.id)
    try:
        return inspect_commerce_story_baseline(
            db,
            page,
            baseline_key=baseline_key,
            workspace_id=workspace.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _validate_baseline_asset(
    db: Session,
    asset_id: str | None,
    project_id: str,
    *,
    field_name: str,
    must_be_jpg: bool,
) -> None:
    if asset_id is None:
        return
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.project_id == project_id).first()
    if asset is None:
        raise HTTPException(status_code=422, detail=f"{field_name} must belong to this project")
    if not asset.mime_type.startswith("image/"):
        raise HTTPException(status_code=422, detail=f"{field_name} must reference an image asset")
    if field_name == "reference_capture_asset_id" and resolved_asset_usage_status(asset) != "reference_only":
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must be marked reference_only",
        )
    if must_be_jpg and not (
        asset.mime_type == "image/jpeg" or asset.filename.lower().endswith((".jpg", ".jpeg"))
    ):
        raise HTTPException(status_code=422, detail=f"{field_name} must reference a JPG export")
    if must_be_jpg and asset.source_type != "exported_image":
        raise HTTPException(status_code=422, detail=f"{field_name} must reference an exported JPG asset")


@router.post("/projects/{project_id}/page/finalize", response_model=FinalPageVersionResponseSchema)
def finalize_page_endpoint(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    get_project_or_404(db, project_id, workspace.id)
    get_visual_ready_page_or_404(db, project_id, workspace.id)

    from src.services.commerce_content_quality_service import inspect_content_quality
    page = get_visual_ready_page_or_404(db, project_id, workspace.id)
    quality = inspect_content_quality(page, db)
    if not quality["ready_for_sale"]:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "판매용 품질 확인 항목을 해결하거나 사용 확인한 뒤 최종본을 만들 수 있습니다.",
                "content_quality": quality,
            },
        )
    try:
        return finalize_page(db, project_id)
    except PageDraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/page/final", response_model=FinalPageVersionResponseSchema)
def get_final_page_endpoint(
    project_id: str,
    version_id: Optional[str] = None,
    channel: Optional[str] = None,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    get_project_or_404(db, project_id, workspace.id)

    try:
        version = get_page_version_for_export(db, project_id, version_id) if version_id else get_final_page_version(db, project_id)
        snapshot = version.sections_json if isinstance(version.sections_json, dict) else {}
        if snapshot.get("schema_version") == "lg10-detail-page-version-v1" and isinstance(snapshot.get("lg11"), dict):
            from src.services.page_visual_contract import LG11CanvasSafetyError, ensure_lg11_canvas_safe
            if channel not in {"smartstore", "coupang"}:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "LG-11 preview requires an explicit channel identity.",
                        "canvas_safety": {
                            "schema_version": "lg11-canvas-safety-v1",
                            "channel": channel,
                            "safe": False,
                            "checked": True,
                            "issues": [{"code": "channel_identity_required", "reason": "A channel must be selected for LG-11 preview."}],
                        },
                    },
                )
            try:
                ensure_lg11_canvas_safe(version_snapshot=snapshot, channel=channel)
            except LG11CanvasSafetyError as exc:
                raise HTTPException(status_code=409, detail={"message": str(exc), "canvas_safety": exc.result}) from exc
        return version
    except FinalPageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/projects/{project_id}/page", response_model=PageResponseSchema)
def save_page_details(
    project_id: str,
    req: UpdatePageRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    user = auth_ctx["user"]
    workspace = auth_ctx["workspace"]
    page = get_page_or_404(db, project_id, workspace.id)
    if not page:
        raise HTTPException(status_code=404, detail="Page draft not found")

    if req.expected_version_id:
        latest_version = (
            db.query(DetailPageVersion)
            .filter(DetailPageVersion.project_id == project_id)
            .order_by(DetailPageVersion.created_at.desc())
            .first()
        )
        if latest_version and latest_version.id != req.expected_version_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "page_version_conflict",
                    "message": "다른 수정이 먼저 저장되었습니다. 최신 버전을 불러온 뒤 다시 저장해 주세요.",
                    "latest_version_id": latest_version.id,
                },
            )

    # 2. 현재 페이지 정보 업데이트
    if req.theme_color is not None:
        page.theme_color = req.theme_color
    if req.font_family is not None:
        page.font_family = req.font_family

    # 3. 개별 섹션 정보 루프 업데이트
    sections_dict = {sec.id: sec for sec in page.sections}
    from src.services.rule_based_copy_service import unsupported_claims
    acknowledged_claims_by_section: dict[str, list[str]] = {}
    for sec_update in req.sections:
        if sec_update.id not in sections_dict:
            raise HTTPException(
                status_code=400,
                detail=f"Section '{sec_update.id}' does not belong to this page",
            )
        if sec_update.image_asset_id and not get_page_eligible_asset(
            db, project_id, sec_update.image_asset_id
        ):
            raise HTTPException(
                status_code=422,
                detail="Image asset is not eligible for page rendering",
            )
        current_section = sections_dict[sec_update.id]
        requested_image_asset_id = sec_update.image_asset_id or None
        image_asset_changed = (
            "image_asset_id" in sec_update.model_fields_set
            and requested_image_asset_id != current_section.image_asset_id
        )
        if (
            image_asset_changed
            and requested_image_asset_id
            and current_section.section_type == "hero"
        ):
            asset = get_page_eligible_asset(db, project_id, sec_update.image_asset_id)
            hero_warning_codes = {
                "LOW_RESOLUTION",
                "EXTREME_ASPECT_RATIO",
                "DUPLICATE_FILE",
                "IMAGE_INTEGRITY_WARNING",
                "SAFE_CROP_REVIEW_REQUIRED",
            }
            if (
                asset
                and hero_warning_codes.intersection(asset.quality_warnings or [])
                and not req.confirm_low_quality_hero
            ):
                raise HTTPException(
                    status_code=409,
                    detail="This image has quality warnings. Confirm before using it as the HERO image.",
                )
        edited_text = f"{sec_update.title or ''} {sec_update.body_copy or ''}"
        unsupported = unsupported_claims(edited_text)
        if unsupported and not req.confirm_unsupported_claims:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "unsupported_claim_requires_review",
                    "section_id": sec_update.id,
                    "claims": unsupported,
                    "message": "근거가 확인되지 않은 효능·인증·보증 표현입니다. 사실 근거를 확인한 뒤 다시 입력해 주세요.",
                },
            )
        if unsupported:
            acknowledged_claims_by_section[sec_update.id] = unsupported

    requested_by_id = {section.id: section for section in req.sections}
    candidate_sections = [
        SimpleNamespace(
            section_type=section.section_type,
            sort_order=(requested_by_id[section.id].sort_order if section.id in requested_by_id else section.sort_order),
            is_visible=(requested_by_id[section.id].is_visible if section.id in requested_by_id else section.is_visible),
        )
        for section in page.sections
    ]
    if not final_spec_is_last(candidate_sections):
        raise HTTPException(
            status_code=422,
            detail="Final product specifications and required notices must be the last visible section.",
        )

    from src.services.page_visual_contract import normalize_visual, validate_visual

    for sec_update in req.sections:
        sec = sections_dict[sec_update.id]
        selection_marker: dict[str, Any] | None = None
        image_asset_changed = False
        if sec_update.title is not None:
            sec.title = sec_update.title
        if sec_update.body_copy is not None:
            sec.body_copy = sec_update.body_copy
        if "image_asset_id" in sec_update.model_fields_set:
            requested_image_asset_id = sec_update.image_asset_id or None
            image_asset_changed = requested_image_asset_id != sec.image_asset_id
            if image_asset_changed:
                sec.image_asset_id = requested_image_asset_id
                selection_marker = {
                    "ux2c_selection_state": (
                        "manual_image" if sec.image_asset_id else "manual_text"
                    ),
                    "asset_id": sec.image_asset_id,
                }
            # Selecting a real candidate resolves the temporary Sprint 1
            # photo/source-approval placeholder. Keep the visual payload from
            # advertising a missing image after the asset has been applied.
            if image_asset_changed and sec.image_asset_id and sec.visual_payload:
                sec.visual_payload = {
                    key: value
                    for key, value in sec.visual_payload.items()
                    if key != "missing_state"
                }
            if image_asset_changed and sec.section_type == "hero":
                payload = dict(sec.visual_payload or {})
                selected_asset = (
                    get_page_eligible_asset(db, project_id, sec.image_asset_id)
                    if sec.image_asset_id
                    else None
                )
                hero_warning_codes = {
                    "LOW_RESOLUTION",
                    "EXTREME_ASPECT_RATIO",
                    "DUPLICATE_FILE",
                    "IMAGE_INTEGRITY_WARNING",
                    "SAFE_CROP_REVIEW_REQUIRED",
                }
                if (
                    selected_asset
                    and hero_warning_codes.intersection(selected_asset.quality_warnings or [])
                    and req.confirm_low_quality_hero
                ):
                    payload["low_quality_hero_confirmed"] = True
                else:
                    payload.pop("low_quality_hero_confirmed", None)
                sec.visual_payload = payload
        if sec_update.visual_kind is not None:
            sec.visual_kind = sec_update.visual_kind
        if sec_update.visual_payload is not None:
            # Keep server-owned review evidence even when the client sends its
            # full visual payload back with an otherwise unrelated edit.
            server_payload = dict(sec.visual_payload or {})
            sec.visual_payload = dict(sec_update.visual_payload)
            if server_payload.get("low_quality_hero_confirmed"):
                sec.visual_payload["low_quality_hero_confirmed"] = True
            # Quality acknowledgements are server evidence. A broad client
            # PATCH (for example changing a title) must not erase who checked
            # an OCR/duplicate warning or when they checked it.
            if server_payload.get("ux2d_quality_acknowledgements"):
                sec.visual_payload["ux2d_quality_acknowledgements"] = server_payload["ux2d_quality_acknowledgements"]
        if selection_marker is not None:
            sec.visual_payload = {
                **dict(sec.visual_payload or {}),
                **selection_marker,
            }
        if sec.id in acknowledged_claims_by_section:
            payload = dict(sec.visual_payload or {})
            payload["unsupported_claim_review"] = {
                "claims": acknowledged_claims_by_section[sec.id],
                "acknowledged_by": user.id,
                "status": "seller_reconfirmation_required",
            }
            sec.visual_payload = payload

        # Validate visual contract if visual fields are provided
        if sec_update.visual_kind is not None or sec_update.visual_payload is not None:
            visual = normalize_visual(
                section_type=sec.section_type,
                image_asset_id=sec.image_asset_id,
                visual_kind=sec.visual_kind,
                visual_payload=sec.visual_payload or {},
            )
            issues = validate_visual(visual)
            if issues:
                raise HTTPException(
                    status_code=422,
                    detail={"section_id": sec.id, "issues": issues},
                )

        sec.sort_order = sec_update.sort_order
        sec.is_visible = sec_update.is_visible

    db.commit()
    db.refresh(page)
    backfill_page_visuals(db, project_id)
    page = get_page_or_404(db, project_id, workspace.id)

    # 4. 수정 완료 후 새 버전 스냅샷 저장
    from src.services.page_version_service import create_page_version
    create_page_version(
        project_id=project_id,
        name="사용자 수정",
        sections=create_page_snapshot(page, db),
        style_key=page.project.selected_style or "problem_solution",
        db=db
    )

    return build_page_response(page, db)



@router.get("/projects/{project_id}/page/versions", response_model=List[PageVersionResponseSchema])
def list_page_versions_endpoint(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    get_project_or_404(db, project_id, workspace.id)
    
    from src.services.page_version_service import list_page_versions as get_versions
    versions = get_versions(project_id, db=db)
    versions = sorted(versions, key=lambda v: v.created_at, reverse=True)
    return [
        {
            "id": version.id,
            "project_id": version.project_id,
            "name": version.name,
            "style_key": version.style_key,
            "is_final": version.is_final,
            "created_at": version.created_at,
            "lg11_frozen": isinstance(getattr(version, "sections_json", None), dict)
            and isinstance(version.sections_json.get("lg11"), dict),
        }
        for version in versions
    ]


@router.get("/projects/{project_id}/page/versions/{version_id}", response_model=PageVersionSnapshotSchema)
def get_page_version_snapshot_endpoint(
    project_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Return a read-only snapshot for Sprint 6 before/after comparison."""
    workspace = auth_ctx["workspace"]
    get_project_or_404(db, project_id, workspace.id)
    version = db.query(DetailPageVersion).filter(
        DetailPageVersion.id == version_id,
        DetailPageVersion.project_id == project_id,
    ).first()
    if not version:
        raise HTTPException(status_code=404, detail="Page version not found")
    return version


def _lg11_edit_request_payload(
    *,
    request: EditIntentPreviewRequest,
    db: Session,
    workspace_id: str,
) -> dict[str, Any]:
    """Pin a requested Brand Kit version before an LG-11 edit is previewed."""

    payload = request.model_dump()
    requested_brand_version_id = str(payload.pop("brand_kit_version_id", "") or "")
    selected_section_id = str(payload.pop("selected_section_id", "") or "").strip() or None
    selected_element_id = str(payload.pop("selected_element_id", "") or "").strip() or None
    if selected_element_id and not selected_section_id:
        raise EditIntentValidationError("An LG-11 selected element requires its selected section identity.")
    if any(value and any(marker in value.lower() for marker in ("<", ">", "javascript:", "http://", "https://", "data:")) for value in (selected_section_id, selected_element_id)):
        raise EditIntentValidationError("LG-11 selected Canvas identities must be stable local IDs.")
    if selected_section_id or selected_element_id:
        constraints = dict(payload.get("preserve_constraints") or {})
        if "selected_context" in constraints:
            raise EditIntentValidationError("LG-11 selected Canvas context is supplied only by the request identity fields.")
        constraints["selected_context"] = {
            "section_id": selected_section_id,
            "element_id": selected_element_id,
        }
        payload["preserve_constraints"] = constraints
    if requested_brand_version_id:
        version = db.query(BrandKitVersion).filter(
            BrandKitVersion.id == requested_brand_version_id,
            BrandKitVersion.workspace_id == workspace_id,
        ).one_or_none()
        if version is None:
            raise EditIntentValidationError("LG-11 style edit Brand Kit version is not in this workspace.")
        payload["brand_kit_ref"] = {
            "brand_kit_version_id": version.id,
            "brand_kit_hash": str(version.content_hash or ""),
        }
    else:
        payload["brand_kit_ref"] = None
    return payload


@router.post("/projects/{project_id}/page/versions/{version_id}/edit-intents/preview")
def preview_edit_intent_endpoint(
    project_id: str,
    version_id: str,
    req: EditIntentPreviewRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Show the frozen-version impact of an LG-11 edit without starting an edit run."""

    workspace = auth_ctx["workspace"]
    get_project_or_404(db, project_id, workspace.id)
    try:
        version = get_page_version_for_export(db, project_id, version_id)
        return preview_lg11_edit_intent(
            version=version,
            **_lg11_edit_request_payload(
                request=req,
                db=db,
                workspace_id=workspace.id,
            ),
        )
    except (FinalPageNotFoundError, EditIntentValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/projects/{project_id}/page/versions/{version_id}/edit-runs",
    response_model=EditRunStartResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_lg11_edit_run_endpoint(
    project_id: str,
    version_id: str,
    req: EditIntentPreviewRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Start a dedicated LG-11 confirmation run from one final frozen version."""

    workspace = auth_ctx["workspace"]
    get_project_or_404(db, project_id, workspace.id)
    try:
        version = get_page_version_for_export(db, project_id, version_id)
        if not version.is_final and not (req.scope == "page" and req.operation == "restore"):
            raise EditIntentValidationError("LG-11 edit runs require a final frozen DetailPageVersion.")
        preview = preview_lg11_edit_intent(
            version=version,
            **_lg11_edit_request_payload(
                request=req,
                db=db,
                workspace_id=workspace.id,
            ),
        )
    except (FinalPageNotFoundError, EditIntentValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    intent = dict(preview["edit_intent"])
    snapshot_hash = str(intent["base_snapshot_hash"])
    run_id = str(uuid.uuid4())
    edit_state = {
        "schema_version": "lg11-edit-run-v1",
        "lineage": {
            "edit_run_id": run_id,
            "source_detail_page_version_id": version.id,
            "parent_detail_page_version_id": version.id,
        },
        "base_version": {"id": version.id, "snapshot_hash": snapshot_hash},
        "intent_id": str(intent["intent_hash"]),
        "intent_hash": str(intent["intent_hash"]),
        "impact_preview": dict(preview["impact_preview"]),
        "confirmation": {"status": "pending"},
    }
    run = AgentRun(
        id=run_id,
        workspace_id=workspace.id,
        project_id=project_id,
        created_by=auth_ctx["user"].id,
        mode="lg11_edit",
        status="created",
        current_stage="edit_intent",
        input_snapshot={
            "lg11_edit": edit_state,
            # Keep the complete immutable request only in the SQL run input.
            # The LangGraph checkpoint contains the stable intent identity and
            # preview, never mutable page state.
            "lg11_edit_intent": intent,
        },
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    from src.services.langgraph_run_service import LangGraphRunService

    try:
        started = LangGraphRunService.start(run.id, workspace.id, db)
        state = LangGraphRunService.get_state(started.id, workspace.id, db)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return EditRunStartResponse(
        run_id=started.id,
        source_detail_page_version_id=version.id,
        parent_detail_page_version_id=version.id,
        intent_id=str(intent["intent_hash"]),
        state={
            "status": state.status,
            "current_stage": state.current_stage,
            "checkpoint_id": state.checkpoint_id,
            "values": state.values,
            "next_nodes": state.next_nodes,
        },
    )


@router.post(
    "/projects/{project_id}/page/sections",
    response_model=SectionResponseSchema,
    status_code=status.HTTP_201_CREATED
)
def add_page_section(
    project_id: str,
    req: SectionCreateSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    page = get_page_or_404(db, project_id, workspace.id)

    if req.image_asset_id:
        asset = get_page_eligible_asset(db, project_id, req.image_asset_id)
        if not asset:
            raise HTTPException(
                status_code=400,
                detail="Image asset is not eligible for page rendering",
            )

    if req.sort_order is None:
        max_sort_order = max((section.sort_order for section in page.sections), default=-1)
        sort_order = max_sort_order + 1
    else:
        sort_order = req.sort_order

    candidate_sections = [
        SimpleNamespace(
            section_type=existing.section_type,
            sort_order=existing.sort_order,
            is_visible=existing.is_visible,
        )
        for existing in page.sections
    ]
    candidate_sections.append(
        SimpleNamespace(section_type=req.section_type, sort_order=sort_order, is_visible=True)
    )
    if not final_spec_is_last(candidate_sections):
        raise HTTPException(
            status_code=422,
            detail="Final product specifications and required notices must be the last visible section.",
        )

    section = PageSection(
        page_id=page.id,
        section_type=req.section_type,
        title=req.title,
        body_copy=req.body_copy,
        associated_fact_ids=req.associated_fact_ids,
        image_asset_id=req.image_asset_id,
        visual_kind=req.visual_kind,
        visual_payload=req.visual_payload,
        sort_order=sort_order,
        is_visible=True
    )
    db.add(section)
    db.commit()
    db.refresh(section)
    db.refresh(page)
    backfill_page_visuals(db, project_id)
    section = db.query(PageSection).filter(PageSection.id == section.id).first()
    page = get_page_or_404(db, project_id, workspace.id)

    from src.services.page_version_service import create_page_version
    create_page_version(
        project_id=project_id,
        name="사용자 섹션 추가",
        sections=create_page_snapshot(page, db),
        style_key=page.project.selected_style or "problem_solution",
        db=db
    )

    return build_section_response(section, db)



@router.post("/projects/{project_id}/page/sections/{section_id}/regenerate", response_model=SectionResponseSchema)
def regenerate_page_section(
    project_id: str,
    section_id: str,
    req: RegenerateSectionRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    page = get_page_or_404(db, project_id, workspace.id)

    section = db.query(PageSection).filter(PageSection.id == section_id, PageSection.page_id == page.id).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found in this page")

    # Claude 3.5 Sonnet 연동 부분 AI 수정
    # 실제로는 유저 instruction을 바탕으로 어댑터나 생성 모델을 구동.
    # 테스트 및 Mock 검증 조건을 지원하기 위해 가이드형 수정 적용.
    original_copy = section.body_copy or ""
    
    # Mock / Simple 로직: 프롬프트 피드백을 문체에 엮어 본문 카피 수정
    if settings.FACTORY_RAG_RUNTIME_MOCK or not settings.ANTHROPIC_API_KEY:
        new_copy = f"{original_copy} [AI 수정 반영: {req.user_instruction}]"
    else:
        try:
            # Anthropic API 클라이언트 직접 호출
            client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            prompt = (
                f"당신은 상세페이지 판매 카피 전문가입니다.\n"
                f"기존 판매 문구: '{original_copy}'\n"
                f"수정 지침: '{req.user_instruction}'\n"
                f"기존 문구를 수정 지침에 맞게 더욱 매력적인 한국어 판매 문구로 새로 작성해 주십시오. 다른 설명 문구 없이 최종 결과물 문구만 출력하십시오."
            )
            response = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            new_copy = response.content[0].text.strip()
        except Exception as e:
            logger.error(f"섹션 AI 재생성 중 오류 발생: {e}. Mock 폴백.", exc_info=True)
            new_copy = f"{original_copy} [AI 수정 반영: {req.user_instruction}]"

    section.body_copy = new_copy
    db.commit()
    db.refresh(section)
    db.refresh(page)

    from src.services.page_version_service import create_page_version
    create_page_version(
        project_id=project_id,
        name="AI 섹션 재생성",
        sections=create_page_snapshot(page, db),
        style_key=page.project.selected_style or "problem_solution",
        db=db
    )

    return build_section_response(section, db)



@router.post("/projects/{project_id}/page/versions/{version_id}/restore", response_model=PageResponseSchema)
def restore_page_version_endpoint(
    project_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    page = get_page_or_404(db, project_id, workspace.id)

    from src.services.page_version_service import restore_page_version as get_version
    version = get_version(version_id, db=db)
    if not version or version.project_id != project_id:
        raise HTTPException(status_code=404, detail="Page version not found")

    snapshot = version.sections_json

    if isinstance(snapshot, dict):
        page.theme_color = snapshot.get("theme_color", page.theme_color)
        page.font_family = snapshot.get("font_family", page.font_family)
        sections_data = snapshot.get("sections", [])
    else:
        sections_data = snapshot

    candidate_sections = [
        SimpleNamespace(
            section_type=section.get("section_type") or section.get("key"),
            sort_order=section.get("sort_order", index),
            is_visible=section.get("is_visible", True),
        )
        for index, section in enumerate(sections_data)
    ]
    if not final_spec_is_last(candidate_sections):
        raise HTTPException(
            status_code=422,
            detail="The selected version places final product specifications before another visible section.",
        )

    # 3. 기존 섹션을 모두 제거한 뒤 선택한 버전의 섹션으로 교체한다.
    db.query(PageSection).filter(PageSection.page_id == page.id).delete()

    for idx, sec_snap in enumerate(sections_data):
        restored_section = PageSection(
            page_id=page.id,
            section_type=sec_snap.get("section_type") or sec_snap.get("key"),
            title=sec_snap.get("title"),
            body_copy=sec_snap.get("body_copy") or sec_snap.get("body"),
            associated_fact_ids=sec_snap.get("associated_fact_ids") or [],
            image_asset_id=sec_snap.get("image_asset_id"),
            visual_kind=sec_snap.get("visual_kind"),
            visual_payload=sec_snap.get("visual_payload") or {},
            sort_order=sec_snap.get("sort_order", idx),
            is_visible=sec_snap.get("is_visible", True),
            facts_stale=bool(sec_snap.get("facts_stale", False)),
        )
        db.add(restored_section)

    db.commit()
    db.refresh(page)

    # Restoring is itself an edit and must be recoverable like all other
    # Sprint 6 block operations.
    from src.services.page_version_service import create_page_version
    create_page_version(
        project_id=project_id,
        name="버전 복원",
        sections=create_page_snapshot(page, db),
        style_key=page.project.selected_style or "commerce_story",
        db=db,
    )

    return build_page_response(page, db)


@router.post("/projects/{project_id}/page/versions/{version_id}/final", response_model=PageVersionResponseSchema)
def mark_page_version_final_endpoint(
    project_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    get_project_or_404(db, project_id, workspace.id)

    from src.services.page_version_service import mark_final_version
    version = mark_final_version(version_id, db=db)
    if not version or version.project_id != project_id:
        raise HTTPException(status_code=404, detail="Page version not found")

    return version


@router.get("/projects/{project_id}/page/grounding-review")
def get_page_grounding_review(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    page = get_page_or_404(db, project_id, workspace.id)
    
    confirmed_facts = db.query(ProductFact).filter(
        ProductFact.project_id == project_id,
        ProductFact.verification_status.in_(CONFIRMED_FACT_STATUSES)
    ).all()
    facts_list = [f.fact_text for f in confirmed_facts]
    
    sections_data = [
        {
            "key": str(sec.id),
            "title": sec.title or "",
            "body": sec.body_copy or "",
        }
        for sec in page.sections
    ]
    
    from src.services.grounding_validator import build_grounding_review
    return build_grounding_review(sections_data, facts_list)


class AutoMapImagesRequest(BaseModel):
    overwrite: bool = Field(False, description="기존 매핑 덮어쓰기 여부")


class ImageAssignmentSchema(BaseModel):
    section_id: str
    section_type: str
    asset_id: str
    filename: str
    asset_role: str
    confidence: float
    reason: str


class AutoMapImagesResponse(BaseModel):
    project_id: str
    assigned_count: int
    skipped_count: int
    missing_roles: List[str]
    assignments: List[ImageAssignmentSchema]


@router.post("/projects/{project_id}/page/auto-map-images", response_model=AutoMapImagesResponse)
def auto_map_images_endpoint(
    project_id: str,
    payload: AutoMapImagesRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    project = get_project_or_404(db, project_id, workspace.id)
    page = db.query(ProductPage).filter(ProductPage.project_id == project_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found for this project")

    # Fetch sections and image assets
    sections = page.sections
    from src.services.image_asset_inspector import backfill_project_asset_metadata
    backfill_project_asset_metadata(project_id, db)
    assets = get_page_eligible_assets(db, project_id)

    # Convert SQLAlchemy objects to dicts for mapper
    sections_data = []
    for sec in sections:
        sections_data.append({
            "id": sec.id,
            "section_type": sec.section_type or "",
            "image_asset_id": sec.image_asset_id
        })

    assets_data = []
    for asset in assets:
        assets_data.append({
            "id": asset.id,
            "filename": asset.filename,
            "mime_type": asset.mime_type,
            "source_type": asset.source_type,
            "asset_role": asset.asset_role,
            "role_confidence": asset.role_confidence,
            "quality_status": asset.quality_status,
            "quality_warnings": asset.quality_warnings or [],
            "content_hash": asset.content_hash,
            "ocr_text": asset.ocr_text,
            "is_representative": asset.is_representative,
        })

    from src.services.image_asset_mapper import (
        find_missing_image_roles,
        map_with_upload_order_fallback,
    )
    assignments = map_with_upload_order_fallback(sections_data, assets_data)
    missing_roles = find_missing_image_roles(
        sections_data, assets_data, assignments
    )

    assigned_count = 0
    skipped_count = 0
    result_assignments = []

    # Map sections by ID for quick access
    sec_map = {sec.id: sec for sec in sections}

    for assignment in assignments:
        sec_id = assignment["section_id"]
        sec = sec_map.get(sec_id)
        if not sec:
            continue

        # Preserve both an explicit photo and an explicit text-only choice.
        selection_state = dict(sec.visual_payload or {}).get("ux2c_selection_state")
        if not payload.overwrite and (
            sec.image_asset_id or selection_state in {"manual_image", "manual_text"}
        ):
            skipped_count += 1
            continue

        sec.image_asset_id = assignment["asset_id"]
        sec.visual_kind = "image"
        sec.visual_payload = {
            **dict(sec.visual_payload or {}),
            "asset_id": assignment["asset_id"],
            "image_assignment": {
                "asset_role": assignment["asset_role"],
                "confidence": assignment["confidence"],
                "reason": assignment["reason"],
            },
            "ux2c_selection_state": "automatic",
        }
        assigned_count += 1
        result_assignments.append(ImageAssignmentSchema(
            section_id=sec_id,
            section_type=assignment["section_type"],
            asset_id=assignment["asset_id"],
            filename=assignment["filename"],
            asset_role=assignment["asset_role"],
            confidence=assignment["confidence"],
            reason=assignment["reason"]
        ))

    # A mapped primary photo can now be rendered by the shared Sprint 3 HERO
    # component.  Do this before snapshotting so preview and export agree.
    from src.services.hero_composition import apply_composed_product_hero
    apply_composed_product_hero(page, db, project.selected_style)
    db.commit()
    db.refresh(page)

    # Create new snapshot and version
    from src.services.page_version_service import create_page_version
    create_page_version(
        project_id=project_id,
        name="자동 이미지 매핑 실행",
        sections=create_page_snapshot(page, db),
        style_key=project.selected_style or "problem_solution",
        db=db
    )

    return AutoMapImagesResponse(
        project_id=project_id,
        assigned_count=assigned_count,
        skipped_count=skipped_count,
        missing_roles=missing_roles,
        assignments=result_assignments
    )


@router.post("/projects/{project_id}/page/figma/export")
def export_page_to_figma(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    user = auth_ctx["user"]
    workspace = auth_ctx["workspace"]
    # 1. Verify project permission
    project = db.query(ProductProject).filter(
        ProductProject.id == project_id,
        ProductProject.workspace_id == workspace.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 2. Check if page exists, else return 409
    page = db.query(ProductPage).filter(ProductPage.project_id == project_id).first()
    if not page:
        raise HTTPException(
            status_code=409,
            detail="Page draft not found for this project. Please generate a page draft first."
        )

    # 3. Build Figma design payload
    from src.services.figma_design_payload_builder import build_figma_design_payload
    payload = build_figma_design_payload(project, page, db)

    # 4. Invoke Figma MCP adapter
    from src.services.figma_mcp_adapter import FigmaMcpAdapter
    adapter = FigmaMcpAdapter()
    adapter_res = adapter.export_to_figma(payload)

    # Gather status/message from adapter response
    status = "exported" if adapter_res.get("success") else "ready"
    message = adapter_res.get("message") or adapter_res.get("reason") or "Figma export processed."

    return {
        "status": status,
        "mcp_status": adapter_res.get("status", "unknown"),
        "payload": payload,
        "message": message
    }


# =====================================================================
# Live Figma Export Endpoints (Sprint 33)
# =====================================================================
import hashlib
import json
from fastapi import BackgroundTasks
from src.db.models import FigmaExportJob

class LiveExportRequest(BaseModel):
    target_file_url: str


def perform_figma_live_export(job_id: str, payload: dict, target_file_url: str, db: Session = None):
    from src.db.database import SessionLocal
    from src.services.figma_bridge_client import FigmaBridgeClient
    
    is_local_db = False
    if db is None:
        db = SessionLocal()
        is_local_db = True
        
    try:
        job = db.query(FigmaExportJob).filter(FigmaExportJob.id == job_id).first()
        if not job:
            return
        
        # 1. Update status to authenticating
        job.status = "authenticating"
        db.commit()

        job.status = "rendering"
        db.commit()

        # 2. Trigger Figma bridge client
        client = FigmaBridgeClient()
        res = client.trigger_export(job_id, target_file_url, payload)
        
        if res.get("success"):
            job.status = "completed"
            job.result_file_url = res.get("result_file_url")
            job.result_node_url = res.get("result_node_url")
            job.error_code = None
            job.error_message = None
            job.auth_url = None
        else:
            job.status = "failed"
            job.error_code = res.get("error_code") or "RENDER_FAILED"
            job.error_message = res.get("error_message") or "Export failed."
            job.auth_url = res.get("auth_url")
        db.commit()
    except Exception as exc:
        try:
            job = db.query(FigmaExportJob).filter(FigmaExportJob.id == job_id).first()
            if job:
                job.status = "failed"
                job.error_code = "RENDER_FAILED"
                job.error_message = str(exc)
                db.commit()
        except Exception:
            pass
    finally:
        if is_local_db:
            db.close()


@router.post("/projects/{project_id}/page/figma/live-export")
def trigger_live_export_api(
    project_id: str,
    req_body: LiveExportRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    user = auth_ctx["user"]
    workspace = auth_ctx["workspace"]
    
    # 1. Verify project permission
    project = db.query(ProductProject).filter(
        ProductProject.id == project_id,
        ProductProject.workspace_id == workspace.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 2. Check if page draft exists
    page = db.query(ProductPage).filter(ProductPage.project_id == project_id).first()
    if not page:
        raise HTTPException(
            status_code=409,
            detail="Page draft not found for this project. Please generate a page draft first."
        )

    # 3. Build figma design payload
    from src.services.figma_design_payload_builder import build_figma_design_payload
    payload = build_figma_design_payload(project, page, db)

    # 4. Generate payload hash
    payload_str = json.dumps(payload, sort_keys=True)
    payload_hash = hashlib.sha256(payload_str.encode()).hexdigest()

    # 5. Create or retrieve figma export job
    from src.services.figma_export_job_service import FigmaExportJobService
    job_service = FigmaExportJobService(db)
    job = job_service.get_or_create_job(
        project_id=project_id,
        workspace_id=workspace.id,
        target_file_url=req_body.target_file_url,
        payload_hash=payload_hash
    )

    # 6. If status is queued, trigger background task
    if job.status == "queued":
        background_tasks.add_task(
            perform_figma_live_export,
            job.id,
            payload,
            req_body.target_file_url
        )

    return {
        "job_id": job.id,
        "status": job.status,
        "message": "Figma 내보내기 작업을 시작했습니다."
    }


@router.get("/projects/{project_id}/page/figma/exports/{job_id}")
def get_live_export_status_api(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    user = auth_ctx["user"]
    workspace = auth_ctx["workspace"]
    
    # 1. Verify project permission
    project = db.query(ProductProject).filter(
        ProductProject.id == project_id,
        ProductProject.workspace_id == workspace.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 2. Retrieve job status
    job = db.query(FigmaExportJob).filter(
        FigmaExportJob.id == job_id,
        FigmaExportJob.project_id == project_id
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")

    return {
        "job_id": job.id,
        "status": job.status,
        "result_file_url": job.result_file_url,
        "result_node_url": job.result_node_url,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "auth_url": job.auth_url
    }


@router.post("/projects/{project_id}/page/figma/exports/{job_id}/retry")
def retry_live_export_api(
    project_id: str,
    job_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    user = auth_ctx["user"]
    workspace = auth_ctx["workspace"]
    
    # 1. Verify project permission
    project = db.query(ProductProject).filter(
        ProductProject.id == project_id,
        ProductProject.workspace_id == workspace.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 2. Retrieve job status
    job = db.query(FigmaExportJob).filter(
        FigmaExportJob.id == job_id,
        FigmaExportJob.project_id == project_id
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")

    # 3. Build figma design payload
    page = db.query(ProductPage).filter(ProductPage.project_id == project_id).first()
    if not page:
        raise HTTPException(status_code=409, detail="Page draft not found")

    from src.services.figma_design_payload_builder import build_figma_design_payload
    payload = build_figma_design_payload(project, page, db)

    # 4. Perform retry status reset
    from src.services.figma_export_job_service import FigmaExportJobService
    job_service = FigmaExportJobService(db)
    try:
        job = job_service.retry_export_job(job.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # 5. Enqueue background task
    background_tasks.add_task(
        perform_figma_live_export,
        job.id,
        payload,
        job.target_file_url
    )

    return {
        "job_id": job.id,
        "status": job.status,
        "message": "Figma 내보내기 재시도 작업을 시작했습니다."
    }


# =====================================================================
# Visual Package & Image Generation Contract Endpoints (Sprint 44)
# =====================================================================

class UpdateVisualJobRequest(BaseModel):
    status: Optional[str] = None
    prompt: Optional[str] = None
    source_asset_ids: Optional[List[str]] = None
    preserve_product_identity: Optional[bool] = None
    cost_tier: Optional[str] = None
    output_size: Optional[str] = None


@router.get("/projects/{project_id}/visual-package")
def get_visual_package(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    project = get_project_or_404(db, project_id, workspace.id)
    page = db.query(ProductPage).filter(ProductPage.project_id == project_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found for this project")

    from src.services.visual_package_planner import (
        VisualPackagePlanner,
        build_visual_package_signature,
        resolve_sales_strategy,
    )
    from src.services.sales_strategy_service import generate_sales_strategy
    
    assets = db.query(Asset).filter(Asset.project_id == project_id).all()
    try:
        generated_strategy = generate_sales_strategy(project, db)
    except Exception:
        generated_strategy = None
    strategy = resolve_sales_strategy(project, generated_strategy)

    current_signature = build_visual_package_signature(
        project,
        page,
        assets,
        strategy,
    )
    cached_jobs = project.visual_package_jobs or []
    if (
        cached_jobs
        and all(
            job.get("plan_signature") == current_signature
            for job in cached_jobs
        )
    ):
        return cached_jobs
        
    planner = VisualPackagePlanner()
    jobs = planner.plan_visual_package(project, page, assets, strategy)
    
    jobs_data = [job.model_dump() for job in jobs]
    project.visual_package_jobs = jobs_data
    db.commit()
    
    return jobs_data


@router.post("/projects/{project_id}/visual-package/regenerate")
def regenerate_visual_package(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    project = get_project_or_404(db, project_id, workspace.id)
    page = db.query(ProductPage).filter(ProductPage.project_id == project_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found for this project")

    # Clear cached plan
    project.visual_package_jobs = None
    db.commit()

    from src.services.visual_package_planner import VisualPackagePlanner
    from src.services.sales_strategy_service import generate_sales_strategy
    
    assets = db.query(Asset).filter(Asset.project_id == project_id).all()
    try:
        strategy = generate_sales_strategy(project, db)
    except Exception:
        strategy = None
        
    planner = VisualPackagePlanner()
    jobs = planner.plan_visual_package(project, page, assets, strategy)
    
    jobs_data = [job.model_dump() for job in jobs]
    project.visual_package_jobs = jobs_data
    db.commit()
    db.refresh(project)
    
    return jobs_data


@router.post("/projects/{project_id}/visual-package/jobs/{job_id}/update")
def update_visual_job(
    project_id: str,
    job_id: str,
    payload: UpdateVisualJobRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    project = get_project_or_404(db, project_id, workspace.id)
    page = db.query(ProductPage).filter(ProductPage.project_id == project_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found for this project")
    
    if not project.visual_package_jobs:
        # Auto plan first
        from src.services.visual_package_planner import VisualPackagePlanner
        from src.services.sales_strategy_service import generate_sales_strategy
        assets = db.query(Asset).filter(Asset.project_id == project_id).all()
        try:
            strategy = generate_sales_strategy(project, db)
        except Exception:
            strategy = None
        planner = VisualPackagePlanner()
        jobs = planner.plan_visual_package(project, page, assets, strategy)
        project.visual_package_jobs = [job.model_dump() for job in jobs]
        db.commit()
        db.refresh(project)
        
    jobs = list(project.visual_package_jobs)
    job_idx = -1
    for idx, j in enumerate(jobs):
        if j.get("job_id") == job_id:
            job_idx = idx
            break
            
    if job_idx == -1:
        raise HTTPException(status_code=404, detail=f"Visual Job '{job_id}' not found in planned package")
        
    job_dict = dict(jobs[job_idx])
    
    # 1. Validate asset ownership and file type
    if payload.source_asset_ids:
        for asset_id in payload.source_asset_ids:
            asset = db.query(Asset).filter(Asset.id == asset_id).first()
            if not asset:
                raise HTTPException(status_code=400, detail=f"Asset '{asset_id}' not found.")
            if asset.project_id != project_id:
                raise HTTPException(status_code=400, detail=f"Asset '{asset_id}' does not belong to project '{project_id}'.")
            if not asset.mime_type or not asset.mime_type.startswith("image/"):
                raise HTTPException(status_code=400, detail=f"Asset '{asset_id}' is not an image (mime_type: {asset.mime_type}).")

    # Update fields from payload
    if payload.status is not None:
        job_dict["status"] = payload.status
    if payload.prompt is not None:
        job_dict["prompt"] = payload.prompt
    if payload.source_asset_ids is not None:
        job_dict["source_asset_ids"] = payload.source_asset_ids
    if payload.preserve_product_identity is not None:
        job_dict["preserve_product_identity"] = payload.preserve_product_identity
    if payload.cost_tier is not None:
        job_dict["cost_tier"] = payload.cost_tier
    if payload.output_size is not None:
        job_dict["output_size"] = payload.output_size

    # 2. Auto-generate prompt if status switches/is needs_generation and current prompt is empty or original photo placeholder
    if job_dict.get("status") == "needs_generation":
        current_p = job_dict.get("prompt", "")
        if (not current_p or not current_p.strip() or 
            current_p.startswith("Original product photo used:") or 
            current_p.startswith("Original photo used:")):
            from src.services.visual_package_planner import (
                generate_prompt_suggestion,
                resolve_sales_strategy,
            )
            from src.services.sales_strategy_service import generate_sales_strategy
            from src.services.commerce_visual_cut_builder import build_commerce_visual_cuts
            
            try:
                generated_strategy = generate_sales_strategy(project, db)
            except Exception:
                generated_strategy = None
            strategy = resolve_sales_strategy(project, generated_strategy)
            
            assets = db.query(Asset).filter(Asset.project_id == project_id).all()
            cuts = build_commerce_visual_cuts(page, [{"id": a.id, "filename": a.filename, "mime_type": a.mime_type, "source_type": a.source_type} for a in assets], project)
            cut = next((c for c in cuts if c.section_id == job_dict.get("section_id")), None)
            if cut:
                job_dict["prompt"] = generate_prompt_suggestion(job_dict["role"], cut, project, strategy)

    # 3. Validate via Pydantic ImageGenerationJob
    from src.services.image_generation_contract import ImageGenerationJob
    try:
        validated_job = ImageGenerationJob(**job_dict)
        job_dict = validated_job.model_dump()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Validation failed: {str(e)}")

    # Sync back to corresponding page section's image_asset_id
    sec = next((s for s in page.sections if s.id == job_dict["section_id"]), None)
    if sec:
        if job_dict["status"] == "planned" and job_dict["source_asset_ids"]:
            sec.image_asset_id = job_dict["source_asset_ids"][0]
        else:
            sec.image_asset_id = None

    # The section image is part of the plan input. Stamp the resulting input
    # signature onto every job so this intentional update is not mistaken for
    # an external project change on the next GET.
    from src.services.visual_package_planner import (
        build_visual_package_signature,
        resolve_sales_strategy,
    )
    from src.services.sales_strategy_service import generate_sales_strategy

    assets = db.query(Asset).filter(Asset.project_id == project_id).all()
    try:
        generated_strategy = generate_sales_strategy(project, db)
    except Exception:
        generated_strategy = None
    strategy = resolve_sales_strategy(project, generated_strategy)
    current_signature = build_visual_package_signature(
        project,
        page,
        assets,
        strategy,
    )
    job_dict["plan_signature"] = current_signature
    jobs[job_idx] = job_dict
    for job in jobs:
        job["plan_signature"] = current_signature
    project.visual_package_jobs = jobs

    db.commit()
    db.refresh(project)
    
    return job_dict


@router.post("/projects/{project_id}/visual-package/jobs/{job_id}/recommend")
def recommend_alternative_visual_prompt(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    project = get_project_or_404(db, project_id, workspace.id)
    page = db.query(ProductPage).filter(ProductPage.project_id == project_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found for this project")
    
    if not project.visual_package_jobs:
        # Auto plan first
        from src.services.visual_package_planner import VisualPackagePlanner
        from src.services.sales_strategy_service import generate_sales_strategy
        assets = db.query(Asset).filter(Asset.project_id == project_id).all()
        try:
            strategy = generate_sales_strategy(project, db)
        except Exception:
            strategy = None
        planner = VisualPackagePlanner()
        jobs = planner.plan_visual_package(project, page, assets, strategy)
        project.visual_package_jobs = [job.model_dump() for job in jobs]
        db.commit()
        db.refresh(project)
        
    jobs = list(project.visual_package_jobs)
    job_idx = -1
    for idx, j in enumerate(jobs):
        if j.get("job_id") == job_id:
            job_idx = idx
            break
            
    if job_idx == -1:
        raise HTTPException(status_code=404, detail=f"Visual Job '{job_id}' not found in planned package")
        
    job_dict = dict(jobs[job_idx])
    
    style_variants = [
        "cinematic studio lighting, award winning product photography, 8k resolution.",
        "clean minimalist background, elegant shadow design, commercial product catalog style.",
        "emotional cozy lifestyle presentation, warm ambient sunbeams, organic vibes."
    ]
    
    current_prompt = job_dict.get("prompt", "")
    base_prompt = current_prompt.split(" - Alternative version")[0]
    
    idx_style = len(current_prompt) % len(style_variants)
    selected_style = style_variants[idx_style]
    
    # Keep the strict text exclusion clause at the very end
    exclusion_clause = " Strictly do NOT include any text, words, letters, labels, logos, badges, or certification marks in the image. Focus purely on the visual scene. All text and labels will be overlaid as edit layers later."
    base_prompt_cleaned = base_prompt.replace(exclusion_clause, "").strip()
    
    new_prompt = f"{base_prompt_cleaned} - Alternative version: {selected_style}{exclusion_clause}"
    job_dict["prompt"] = new_prompt
    
    jobs[job_idx] = job_dict
    project.visual_package_jobs = jobs
    db.commit()
    
    return job_dict


@router.get("/projects/{project_id}/detail-page-package", response_model=DetailPagePackage)
def get_detail_page_package(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    get_project_or_404(db, project_id, workspace.id)
    return DetailPagePackageService.get_or_create_detail_page_package(project_id, db)


@router.post("/projects/{project_id}/page/sections/{section_id}/ai-edit", response_model=DetailPagePackage)
def process_ai_edit(
    project_id: str,
    section_id: str,
    payload: AiEditCommandPayload,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "message": "This endpoint is deprecated. Use copy-rewrite preview and apply through page PATCH instead.",
            "new_endpoint": f"/api/v1/projects/{project_id}/page/sections/{section_id}/copy-rewrite/preview",
        },
    )


class CopyRewritePreviewRequest(BaseModel):
    command: CopyRewriteCommand
    title: str | None = None
    body_copy: str | None = None
    instruction: str = ""
    scope: Literal["section"] = "section"


class AiEditCommandRequest(BaseModel):
    section_id: str
    command: str


@router.post(
    "/projects/{project_id}/page/sections/{section_id}/copy-rewrite/preview",
    response_model=CopyRewriteResult,
)
def preview_copy_rewrite(
    project_id: str,
    section_id: str,
    req: CopyRewritePreviewRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    workspace = auth_ctx["workspace"]
    page = get_page_or_404(db, project_id, workspace.id)

    section = db.query(PageSection).filter(
        PageSection.id == section_id,
        PageSection.page_id == page.id,
    ).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")

    confirmed_facts = [
        f.fact_text
        for f in db.query(ProductFact).filter(
            ProductFact.project_id == project_id,
            ProductFact.verification_status.in_(CONFIRMED_FACT_STATUSES),
        ).all()
    ]

    source_title = req.title if req.title is not None else (section.title or "")
    source_body = req.body_copy if req.body_copy is not None else (section.body_copy or "")

    service = CopyRewriteService(mode="mock")
    result = service.preview(
        command=req.command,
        title=source_title,
        body_copy=source_body,
        instruction=req.instruction,
        confirmed_facts=confirmed_facts,
        forbidden_claims=[],
        section_type=section.section_type,
    )
    return result


@router.post("/projects/{project_id}/pages/ai-edit")
def process_ai_edit_command(
    project_id: str,
    payload: AiEditCommandRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    # Deprecated: use /page/sections/{section_id}/copy-rewrite/preview instead
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "message": "This endpoint is deprecated. Use POST /projects/{project_id}/page/sections/{section_id}/copy-rewrite/preview instead.",
            "new_endpoint": f"/api/v1/projects/{project_id}/page/sections/{payload.section_id}/copy-rewrite/preview",
        },
    )



@router.get("/projects/{project_id}/planning-draft", response_model=PlanningDraftSchema)
def get_planning_draft(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    project = get_project_or_404(db, project_id, workspace.id)

    if not project.planning_draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Planning draft not found for this project"
        )

    return PlanningDraftSchema(**project.planning_draft)


@router.post("/projects/{project_id}/planning-draft", response_model=PlanningDraftSchema)
def create_planning_draft(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    project = get_project_or_404(db, project_id, workspace.id)

    confirmed_facts = db.query(ProductFact).filter(
        ProductFact.project_id == project_id,
        ProductFact.verification_status.in_(CONFIRMED_FACT_STATUSES),
    ).all()

    assets = db.query(Asset).filter(Asset.project_id == project_id).all()
    draft = generate_storyboard(project, confirmed_facts, assets, db, auth_ctx["user"].id)
    project.planning_draft = draft
    db.commit()
    db.refresh(project)

    return PlanningDraftSchema(**project.planning_draft)


@router.patch("/projects/{project_id}/planning-draft", response_model=PlanningDraftSchema)
def update_planning_draft(
    project_id: str,
    payload: PlanningDraftSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    project = get_project_or_404(db, project_id, workspace.id)

    existing = project.planning_draft or {}
    draft = {**existing, **payload.model_dump(exclude_unset=True)}
    draft["revision_history"] = existing.get("revision_history") or []
    confirmed_facts = db.query(ProductFact).filter(
        ProductFact.project_id == project_id,
        ProductFact.verification_status.in_(CONFIRMED_FACT_STATUSES),
    ).all()
    assets = db.query(Asset).filter(Asset.project_id == project_id).all()
    try:
        validate_storyboard(draft, assets, {fact.id for fact in confirmed_facts if not fact.needs_review})
    except StoryboardValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    draft["status"] = "draft"
    draft = record_storyboard_revision(draft, "edited")
    project.planning_draft = draft
    db.commit()
    db.refresh(project)

    return PlanningDraftSchema(**project.planning_draft)


@router.get("/projects/{project_id}/generation-plan", response_model=ApiReadyGenerationPlanSchema)
def get_generation_plan(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Return the provider-free UX-2E-0 brief and scene plan."""
    from src.services.api_ready_generation_service import get_generation_plan as get_stored_plan

    project = get_project_or_404(db, project_id, auth_ctx["workspace"].id)
    plan = get_stored_plan(project)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI 생성 준비 계획이 없습니다.")
    return ApiReadyGenerationPlanSchema(**plan)


@router.post("/projects/{project_id}/generation-plan", response_model=ApiReadyGenerationPlanSchema)
def create_generation_plan(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Create/refresh a deterministic plan; this endpoint never calls an AI provider."""
    from src.services.api_ready_generation_service import create_or_refresh_generation_plan

    project = get_project_or_404(db, project_id, auth_ctx["workspace"].id)
    plan = create_or_refresh_generation_plan(project, db)
    db.commit()
    db.refresh(project)
    return ApiReadyGenerationPlanSchema(**plan)


@router.patch("/projects/{project_id}/generation-plan", response_model=ApiReadyGenerationPlanSchema)
def update_generation_plan(
    project_id: str,
    payload: GenerationPlanUpdateSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    from src.services.api_ready_generation_service import update_generation_plan as update_stored_plan

    project = get_project_or_404(db, project_id, auth_ctx["workspace"].id)
    try:
        plan = update_stored_plan(
            project,
            db,
            [item.model_dump(exclude_unset=True) for item in payload.scenes],
            payload.product_brief.model_dump(exclude_unset=True) if payload.product_brief else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    db.commit()
    db.refresh(project)
    return ApiReadyGenerationPlanSchema(**plan)


@router.post("/projects/{project_id}/generation-plan/copy-drafts", response_model=GroundedCopyDraftResponseSchema)
def create_generation_plan_copy_drafts(
    project_id: str,
    payload: GroundedCopyDraftRequestSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Create seller-review-only Korean drafts from confirmed fact IDs."""
    project = get_project_or_404(db, project_id, auth_ctx["workspace"].id)
    if auth_ctx.get("role") not in {"owner", "admin", "member", "editor"}:
        raise HTTPException(status_code=403, detail="카피 생성에는 편집 권한이 필요합니다.")
    from src.services.api_ready_generation_service import get_generation_plan, save_generation_plan
    from src.services.ocr_copy_generation_service import create_grounded_copy_drafts
    plan = get_generation_plan(project)
    if not plan:
        raise HTTPException(status_code=409, detail="상품 브리프·장면 계획을 먼저 만드세요.")
    try:
        result = create_grounded_copy_drafts(db, project, plan, payload.scene_ids or None, payload.seller_cost_approved, auth_ctx["user"].id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    save_generation_plan(project, result["plan"])
    db.commit()
    return GroundedCopyDraftResponseSchema(**result)


@router.get("/projects/{project_id}/generation-plan/copy-drafts/estimate", response_model=GroundedCopyDraftEstimateSchema)
def estimate_generation_plan_copy_drafts(
    project_id: str,
    scene_ids: list[str] | None = None,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    project = get_project_or_404(db, project_id, auth_ctx["workspace"].id)
    from src.services.api_ready_generation_service import get_generation_plan
    from src.services.ocr_copy_generation_service import estimate_grounded_copy_drafts
    plan = get_generation_plan(project)
    if not plan:
        raise HTTPException(status_code=409, detail="상품 브리프·장면 계획을 먼저 만드세요.")
    return GroundedCopyDraftEstimateSchema(**estimate_grounded_copy_drafts(project, plan, scene_ids))


@router.patch("/projects/{project_id}/generation-plan/copy-drafts/{scene_id}")
def decide_generation_plan_copy_draft(
    project_id: str,
    scene_id: str,
    payload: GroundedCopyDraftDecisionSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    project = get_project_or_404(db, project_id, auth_ctx["workspace"].id)
    if auth_ctx.get("role") not in {"owner", "admin", "member", "editor"}:
        raise HTTPException(status_code=403, detail="카피 승인에는 편집 권한이 필요합니다.")
    from src.services.api_ready_generation_service import get_generation_plan, save_generation_plan
    from src.services.ocr_copy_generation_service import decide_copy_draft
    plan = get_generation_plan(project)
    if not plan:
        raise HTTPException(status_code=409, detail="상품 브리프·장면 계획을 먼저 만드세요.")
    try:
        draft = decide_copy_draft(db, project, plan, scene_id, payload.seller_approved)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    save_generation_plan(project, plan)
    db.commit()
    return {"scene_id": scene_id, "copy_draft": draft}


@router.post("/projects/{project_id}/storyboard/recommendations", response_model=PlanningDraftSchema)
def regenerate_storyboard_recommendations(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Build provider-free Sprint 4 candidates from approved facts and assets."""
    workspace = auth_ctx["workspace"]
    project = get_project_or_404(db, project_id, workspace.id)
    confirmed_facts = db.query(ProductFact).filter(
        ProductFact.project_id == project_id,
        ProductFact.verification_status.in_(CONFIRMED_FACT_STATUSES),
    ).all()
    assets = db.query(Asset).filter(Asset.project_id == project_id).all()
    project.planning_draft = generate_storyboard(project, confirmed_facts, assets, db, auth_ctx["user"].id)
    db.commit()
    db.refresh(project)
    return PlanningDraftSchema(**project.planning_draft)


@router.post("/projects/{project_id}/storyboard/select", response_model=PlanningDraftSchema)
def select_storyboard_recommendation(
    project_id: str,
    payload: StoryboardRecommendationSelectSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    workspace = auth_ctx["workspace"]
    project = get_project_or_404(db, project_id, workspace.id)
    if not project.planning_draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Storyboard not found for this project")
    try:
        project.planning_draft = select_recommendation(project.planning_draft, payload.candidate_key)
    except StoryboardValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    db.commit()
    db.refresh(project)
    return PlanningDraftSchema(**project.planning_draft)


@router.post("/projects/{project_id}/storyboard/restore", response_model=PlanningDraftSchema)
def restore_storyboard_draft(
    project_id: str,
    payload: StoryboardRestoreSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    workspace = auth_ctx["workspace"]
    project = get_project_or_404(db, project_id, workspace.id)
    if not project.planning_draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Storyboard not found for this project")
    try:
        restored = restore_storyboard_revision(project.planning_draft, payload.revision)
        facts = db.query(ProductFact).filter(
            ProductFact.project_id == project_id,
            ProductFact.verification_status.in_(CONFIRMED_FACT_STATUSES),
        ).all()
        assets = db.query(Asset).filter(Asset.project_id == project_id).all()
        validate_storyboard(restored, assets, {fact.id for fact in facts if not fact.needs_review})
        project.planning_draft = restored
    except StoryboardValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    db.commit()
    db.refresh(project)
    return PlanningDraftSchema(**project.planning_draft)


@router.post("/projects/{project_id}/storyboard/approve", response_model=PlanningDraftSchema)
def approve_storyboard_draft(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Approve only the storyboard; Sprint 5 owns actual image generation."""
    workspace = auth_ctx["workspace"]
    project = get_project_or_404(db, project_id, workspace.id)
    if not project.planning_draft:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="승인할 스토리보드가 없습니다.")
    facts = db.query(ProductFact).filter(ProductFact.project_id == project_id).all()
    assets = db.query(Asset).filter(Asset.project_id == project_id).all()
    try:
        approve_storyboard(project, assets, facts, db, auth_ctx["user"].id)
    except StoryboardValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    db.commit()
    db.refresh(project)
    return PlanningDraftSchema(**project.planning_draft)


@router.post("/projects/{project_id}/planning-draft/approve")
def approve_planning_draft(
    project_id: str,
    payload: PlanningDraftApprovalRequest | None = None,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    import datetime
    from src.db.models import DetailPageVersion, ImageGenerationJobRecord
    from src.services.image_generation_service import execute_image_generation, sync_job_to_project_json
    from src.services.storyboard_image_generation_service import SCENE_ROLES

    workspace = auth_ctx["workspace"]
    project = get_project_or_404(db, project_id, workspace.id)
    allow_pending_images = bool(payload and payload.allow_pending_images)

    if not project.planning_draft:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="승인할 상세페이지 기획안이 없습니다.",
        )

    cards = project.planning_draft.get("cards") or []
    enabled_cards = [card for card in cards if card.get("is_enabled", True)]
    enabled_cards.sort(key=lambda card: card.get("sort_order", 0))

    # Preserve Sprint 5/7 scene approvals.  The old assembler deleted every
    # image job, then recreated legacy jobs, which disconnected the approved
    # scene images from the page that is assembled below.
    storyboard_jobs = (
        db.query(ImageGenerationJobRecord)
        .filter(
            ImageGenerationJobRecord.project_id == project_id,
            ImageGenerationJobRecord.job_id.like("s5-%"),
        )
        .all()
    )
    storyboard_scene_jobs = {
        job.section_id: job for job in storyboard_jobs if job.section_id
    }
    if storyboard_scene_jobs:
        unfinished_scene_cards = []
        for card in enabled_cards:
            card_id = card.get("id")
            if not card_id or (card.get("type") or "") not in SCENE_ROLES:
                continue
            job = storyboard_scene_jobs.get(card_id)
            if job and (job.status != "approved" or not job.output_asset_id):
                unfinished_scene_cards.append(card.get("title") or card.get("label") or card_id)
        if unfinished_scene_cards and not allow_pending_images:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "승인 이미지로 상세페이지를 만들기 전에 모든 준비 장면의 최종 이미지를 "
                    "업로드하고 '외형 확인 후 사용'을 완료해 주세요: "
                    + ", ".join(unfinished_scene_cards)
                ),
            )

    # 기존 상세페이지와 이미지 생성 job을 교체해 중복 생성을 막는다.
    db.query(ProductPage).filter(ProductPage.project_id == project_id).delete()
    db.query(ImageGenerationJobRecord).filter(
        ImageGenerationJobRecord.project_id == project_id,
        ImageGenerationJobRecord.job_id.like("planning-%"),
    ).delete(synchronize_session=False)
    db.flush()

    page = ProductPage(
        project_id=project_id,
        theme_color="#3B82F6",
        font_family="sans-serif",
    )
    db.add(page)
    db.flush()

    version_sections = []
    image_job_ids: list[str] = []
    project_assets = db.query(Asset).filter(Asset.project_id == project_id).all()
    cutout_asset_ids = [
        asset.id
        for asset in project_assets
        if asset.background_removed
        or asset.cutout_status == "completed"
        or asset.source_type == "ai_corrected"
    ]
    uploaded_product_asset_ids = [
        asset.id
        for asset in project_assets
        if asset.source_type in {"self_shot", "uploaded", "url-extracted", "url-imported", "sourced"}
    ]
    product_reference_asset_ids = cutout_asset_ids or uploaded_product_asset_ids
    # A Sprint 5-approved manual upload or provider output is already a final
    # scene asset.  Rebuilding the page must keep it instead of queueing a
    # second image-provider request (which is especially important for the
    # provider-free manual-upload flow).
    final_assets_by_id = {
        asset.id: asset
        for asset in get_page_eligible_assets(db, project_id)
    }
    identity_preserving_card_types = {
        "hero",
        "lifestyle_scene",
        "lifestyle",
        "detail_1",
        "detail_2",
        "features",
        "cta",
    }
    seen_body_copies: set[str] = set()

    for idx, card in enumerate(enabled_cards):
        visual_strategy = card.get("visual_strategy") or "text_only"
        card_type = card.get("type") or ""
        selected_asset_id = card.get("image_asset_id")
        selected_asset = final_assets_by_id.get(selected_asset_id) if selected_asset_id else None
        if card_type in {"specifications", "comparison", "pre_purchase", "product_information"}:
            needs_image = False
            visual_kind = "html_graphic"
        else:
            needs_image = (
                visual_strategy in {"image_overlay", "lifestyle_image", "graphic_chart"}
                and selected_asset is None
            )
            visual_kind = "image" if needs_image or selected_asset else "html_graphic"
        # "생성 대기 상태" is a strict no-provider path.  This applies not
        # only to Sprint 5 scene jobs but also to legacy image-oriented cards
        # (for example target_customer/lifestyle cards) that would otherwise
        # create and synchronously execute a planning-* generation job below.
        image_generation_pending = bool(
            allow_pending_images
            and not selected_asset
            and (needs_image or (storyboard_scene_jobs and card_type in SCENE_ROLES))
        )
        if image_generation_pending:
            needs_image = False
            visual_kind = "html_graphic"
        body_copy = format_planning_card_body_copy(card)
        normalized_body = " ".join(body_copy.split()).strip().lower()
        if normalized_body and normalized_body in seen_body_copies:
            # Repeating the same single fact in HERO and feature cards makes
            # the freshly assembled page fail its own sale-quality gate. The
            # title/visual still carries the section purpose, so omit only the
            # redundant body instead of inventing replacement copy.
            body_copy = ""
        elif normalized_body:
            seen_body_copies.add(normalized_body)

        section = PageSection(
            page_id=page.id,
            section_type=card_type or f"section_{idx + 1}",
            title=card.get("title") or "",
            body_copy=body_copy,
            associated_fact_ids=card.get("source_fact_ids") or [],
            image_asset_id=selected_asset.id if selected_asset else None,
            visual_kind=visual_kind,
            visual_payload={
                "strategy": visual_strategy,
                "image_generation_pending": image_generation_pending,
                "facts_intentionally_empty": not bool(card.get("source_fact_ids")),
                # A HERO selected through the storyboard's explicit
                # "외형 확인 후 사용" flow is not an automatic low-quality
                # assignment.  Retain that seller decision when the normal
                # page-readiness cleanup runs.
                **(
                    {"low_quality_hero_confirmed": True}
                    if (
                        card_type == "hero"
                        and selected_asset is not None
                        and card.get("image_requirement") == "asset_ready"
                    )
                    else {}
                ),
                # Text-first narrative cards are valid HTML visuals even when
                # they intentionally have no linked product fact or image.
                **(
                    {"layout_variant": "image_text"}
                    if (
                        visual_kind == "html_graphic"
                        and visual_strategy == "text_only"
                        and card_type in {
                            "problem",
                            "target_customer",
                            "caution",
                            "cta",
                            "overall_summary",
                        }
                    )
                    else {}
                ),
            },
            sort_order=idx,
            is_visible=True,
        )
        db.add(section)
        db.flush()

        if needs_image and storyboard_scene_jobs and not allow_pending_images:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "승인된 장면 이미지를 찾을 수 없습니다. 스토리보드에서 해당 장면의 "
                    "최종 이미지를 승인한 뒤 다시 상세페이지를 만들어 주세요: "
                    + (card.get("title") or card.get("label") or card_type)
                ),
            )

        if needs_image:
            job_id = f"planning-{project_id}-{section.id}"
            job_source_asset_ids = (
                product_reference_asset_ids if card_type in identity_preserving_card_types else []
            )
            preserve_product_identity = bool(job_source_asset_ids)
            reference_instruction = (
                "Use the provided product cutout/reference as the fixed product identity. "
                "Preserve the product shape, color, proportions, logo/display details, and key visible features. "
                "Only compose the background, lighting, shadow, and scene around that product."
                if preserve_product_identity
                else "No product reference asset is available. Generate a conservative commerce scene and avoid inventing unverifiable product details."
            )
            job_prompt = (
                f"Product: {project.name}. Section: {section.title}. "
                f"{reference_instruction} "
                "Create a clean commerce image suitable for a product detail page. "
                "Do not put text, logo overlays, watermark, badges, or captions inside the image; "
                "all copy will be rendered separately with HTML/CSS."
            )
            job_record = ImageGenerationJobRecord(
                project_id=project_id,
                job_id=job_id,
                section_id=section.id,
                role=card.get("type") or section.section_type,
                source_asset_ids=job_source_asset_ids,
                prompt=(
                    f"상품명: {project.name}. 섹션 주제: {section.title}. "
                    "상세페이지에 어울리는 깔끔한 상품/라이프스타일 이미지를 생성하세요. "
                    "이미지 안에는 글자, 로고, 워터마크, 배지를 넣지 마세요. "
                    "문구는 HTML/CSS 레이어에서 별도로 렌더링됩니다."
                ),
                negative_prompt="text, letters, logo, watermark, badge, distorted product",
                preserve_product_identity=preserve_product_identity,
                output_size="1024x1024",
                cost_tier="premium",
                status="needs_generation",
            )
            job_record.prompt = job_prompt
            db.add(job_record)
            image_job_ids.append(job_id)

        version_sections.append({
            "id": section.id,
            "key": section.section_type,
            "section_type": section.section_type,
            "title": section.title,
            "body": body_copy,
            "body_copy": body_copy,
            "associated_fact_ids": section.associated_fact_ids or [],
            "image_asset_id": selected_asset.id if selected_asset else None,
            "visual_kind": visual_kind,
            "visual_payload": section.visual_payload or {},
            "sort_order": idx,
            "is_visible": True,
        })

    db.flush()

    generated_candidates: dict[str, list[dict[str, Any]]] = {}
    for job_id in image_job_ids:
        try:
            result = execute_image_generation(project_id, job_id, db, cost_approved=True)
            if result.output_asset_id:
                section = (
                    db.query(PageSection)
                    .filter(PageSection.page_id == page.id, PageSection.id == result.section_id)
                    .first()
                )
                if section:
                    section.image_asset_id = result.output_asset_id
                    result.status = "approved"
                    for version_section in version_sections:
                        if version_section["id"] == section.id:
                            version_section["image_asset_id"] = result.output_asset_id
                            break
            sync_job_to_project_json(project_id, job_id, db)
            generated_candidates.setdefault(result.role, []).append({
                "candidate_id": result.job_id,
                "asset_id": result.output_asset_id,
                "label": "생성 이미지" if result.output_asset_id else "이미지 생성 대기",
                "source_type": "ai_generated",
                "status": result.status,
            })
        except Exception as exc:
            logger.warning("Planning draft image generation failed for %s: %s", job_id, exc)

    run = (
        db.query(AgentRun)
        .filter(AgentRun.project_id == project_id)
        .order_by(AgentRun.created_at.desc())
        .first()
    )
    if run:
        run.status = "completed"
        run.current_stage = "review_editor"
        run.outputs_json = {
            "sales_strategy": {
                "hook_headline": enabled_cards[0].get("title") if enabled_cards else "상세페이지 초안",
                "tone_and_manner": "쉽고 신뢰감 있는 판매 톤",
            },
            "visual_plan": {"color_palette": ["#3B82F6", "#FFFFFF"]},
            "image_generation": {"candidates": generated_candidates},
            "page_assembly": {
                "sections": [
                    {
                        "id": section["id"],
                        "title": section["title"],
                        "body": section["body_copy"],
                        "visual_role": section["section_type"],
                        "image_id": None,
                    }
                    for section in version_sections
                ]
            },
        }
        run.completed_at = datetime.datetime.utcnow()
        db.add(run)

    db.add(
        DetailPageVersion(
            project_id=project_id,
            name="AI 생성 상세페이지",
            style_key="problem_solution",
            sections_json=version_sections,
            is_final=True,
        )
    )

    project.status = "ready"
    db.commit()

    return {
        "status": "success",
        "message": "상세페이지 기획안을 승인하고 이미지 생성을 시작했습니다.",
        "image_job_count": len(image_job_ids),
    }
