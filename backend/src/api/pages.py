# This module uses legacy SQLAlchemy Column declarations whose instance values
# are resolved dynamically at runtime. Pyright otherwise treats them as Column
# objects and reports false positives throughout the API layer.
# pyright: reportArgumentType=false, reportAssignmentType=false, reportReturnType=false, reportGeneralTypeIssues=false, reportCallIssue=false, reportOptionalMemberAccess=false, reportAttributeAccessIssue=false

import logging
import anthropic
from typing import Optional, List, Dict, Any, Literal
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from src.api.auth import get_current_user_and_workspace
from src.config import settings
from src.db.database import get_db
from src.db.models import ProductProject, ProductPage, PageSection, PageVersion, ProductFact, Asset, User, AgentRun, ImageGenerationJobRecord
from src.schemas.planning_draft import PlanningDraftSchema

from src.services.page_generator import PageGenerationService
from src.services.style_strategy_service import generate_style_candidates, get_category_frame, is_valid_style_candidate_key
from src.services.grounding_validator import detect_claim_risks, map_section_to_facts
from src.services.copy_rewrite_service import CopyRewriteCommand, CopyRewriteService, CopyRewriteResult
from src.services.detail_page_package_service import DetailPagePackageService, DetailPagePackage, AiEditCommandPayload
from src.services.page_readiness_service import PageReadiness, inspect_page_readiness
from src.services.page_finalization_service import (
    FinalPageNotFoundError,
    PageDraftNotFoundError,
    finalize_page,
    get_final_page_version,
    get_page_version_for_export,
)
from src.services.page_asset_policy import (
    get_page_eligible_asset,
    get_page_eligible_assets,
)
from src.services.visual_contract_backfill import backfill_page_visuals


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


class SectionUpdateSchema(BaseModel):
    id: str
    title: Optional[str] = None
    body_copy: Optional[str] = None
    image_asset_id: Optional[str] = None
    visual_kind: Optional[Literal["image", "html_graphic"]] = None
    visual_payload: Optional[dict] = None
    sort_order: int
    is_visible: bool

class SectionCreateSchema(BaseModel):
    section_type: str = Field(..., description="섹션 유형(header, features, specifications, faq 등)")
    title: Optional[str] = None
    body_copy: Optional[str] = None
    associated_fact_ids: List[str] = []
    image_asset_id: Optional[str] = None
    visual_kind: Optional[Literal["image", "html_graphic"]] = None
    visual_payload: Optional[dict] = None
    sort_order: Optional[int] = None

class UpdatePageRequest(BaseModel):
    theme_color: Optional[str] = None
    font_family: Optional[str] = None
    sections: List[SectionUpdateSchema]

class RegenerateSectionRequest(BaseModel):
    user_instruction: str = Field(..., description="AI에게 내릴 섹션 수정 요구사항")

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
    image_asset_id: Optional[str]
    visual_kind: Optional[str] = None
    visual_payload: Optional[dict] = None
    sort_order: int
    is_visible: bool
    warnings: List[str] = []
    grounding_warnings: List[GroundingWarningSchema] = []
    matched_facts: List[str] = []
    image_candidates: List[dict] = []

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

    class Config:
        from_attributes = True


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

    return {
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


def get_visual_ready_page_or_404(db: Session, project_id: str, workspace_id: str) -> ProductPage:
    """Load page after idempotently repairing legacy/incomplete visual contracts."""
    page = get_page_or_404(db, project_id, workspace_id)
    report = backfill_page_visuals(db, project_id)
    if report.updated:
        page = get_page_or_404(db, project_id, workspace_id)
    return page


def get_unconfirmed_warnings(db: Session, project_id: str) -> List[str]:
    unconfirmed_facts = db.query(ProductFact).filter(
        ProductFact.project_id == project_id,
        ProductFact.verification_status != "confirmed"
    ).all()
    return [f.fact_text for f in unconfirmed_facts]


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
    return enriched_candidates


def build_section_response(section: PageSection, db: Session) -> SectionResponseSchema:
    project_id = section.page.project_id if section.page else db.query(ProductPage).filter(ProductPage.id == section.page_id).first().project_id
    confirmed_facts = db.query(ProductFact).filter(
        ProductFact.project_id == project_id,
        ProductFact.verification_status == "confirmed"
    ).all()
    facts_list = [f.fact_text for f in confirmed_facts]
    unconfirmed_warnings = get_unconfirmed_warnings(db, project_id)
    
    text = f"{section.title or ''} {section.body_copy or ''}"
    g_warnings = detect_claim_risks(text, facts_list)
    matched_facts = map_section_to_facts(text, facts_list)
    
    candidates_list = get_image_candidates_for_section(section, db, project_id)

    return SectionResponseSchema(
        id=section.id,
        section_type=section.section_type,
        title=section.title,
        body_copy=section.body_copy,
        associated_fact_ids=section.associated_fact_ids,
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
        ProductFact.verification_status == "confirmed"
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
            ProductFact.verification_status == "confirmed"
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
        ProductFact.verification_status == "confirmed"
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
        ProductFact.verification_status == "confirmed"
    ).all()
    
    unconfirmed_facts = db.query(ProductFact).filter(
        ProductFact.project_id == project_id,
        ProductFact.verification_status != "confirmed"
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
            assets_data = [{"id": a.id, "filename": a.filename, "mime_type": a.mime_type, "source_type": a.source_type} for a in image_assets]
            
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

    return build_page_response(page, db)


@router.get("/projects/{project_id}/page/readiness", response_model=PageReadiness)
def get_page_readiness(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    page = get_visual_ready_page_or_404(db, project_id, workspace.id)
    return inspect_page_readiness(page, db)


@router.post("/projects/{project_id}/page/finalize", response_model=FinalPageVersionResponseSchema)
def finalize_page_endpoint(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    get_project_or_404(db, project_id, workspace.id)
    get_visual_ready_page_or_404(db, project_id, workspace.id)

    try:
        return finalize_page(db, project_id)
    except PageDraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/page/final", response_model=FinalPageVersionResponseSchema)
def get_final_page_endpoint(
    project_id: str,
    version_id: Optional[str] = None,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    get_project_or_404(db, project_id, workspace.id)

    try:
        if version_id:
            return get_page_version_for_export(db, project_id, version_id)
        return get_final_page_version(db, project_id)
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

    # 2. 현재 페이지 정보 업데이트
    if req.theme_color is not None:
        page.theme_color = req.theme_color
    if req.font_family is not None:
        page.font_family = req.font_family

    # 3. 개별 섹션 정보 루프 업데이트
    sections_dict = {sec.id: sec for sec in page.sections}
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
                status_code=400,
                detail="Image asset is not eligible for page rendering",
            )

    from src.services.page_visual_contract import normalize_visual, validate_visual

    for sec_update in req.sections:
        sec = sections_dict[sec_update.id]
        if sec_update.title is not None:
            sec.title = sec_update.title
        if sec_update.body_copy is not None:
            sec.body_copy = sec_update.body_copy
        if sec_update.image_asset_id is not None:
            sec.image_asset_id = sec_update.image_asset_id or None
        if sec_update.visual_kind is not None:
            sec.visual_kind = sec_update.visual_kind
        if sec_update.visual_payload is not None:
            sec.visual_payload = sec_update.visual_payload

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
    return versions


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
            sort_order=sec_snap.get("sort_order", idx),
            is_visible=sec_snap.get("is_visible", True)
        )
        db.add(restored_section)

    db.commit()
    db.refresh(page)

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
        ProductFact.verification_status == "confirmed"
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
            "source_type": asset.source_type
        })

    from src.services.image_asset_mapper import (
        find_missing_image_roles,
        map_image_assets_to_sections,
    )
    assignments = map_image_assets_to_sections(sections_data, assets_data)
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

        # If not overwrite and already has image_asset_id, skip it
        if not payload.overwrite and sec.image_asset_id:
            skipped_count += 1
            continue

        sec.image_asset_id = assignment["asset_id"]
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

    db.commit()

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
            ProductFact.verification_status == "confirmed",
        ).all()
    ]

    service = CopyRewriteService(mode="mock")
    result = service.preview(
        command=req.command,
        title=section.title or "",
        body_copy=section.body_copy or "",
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


@router.patch("/projects/{project_id}/planning-draft", response_model=PlanningDraftSchema)
def update_planning_draft(
    project_id: str,
    payload: PlanningDraftSchema,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace)
):
    workspace = auth_ctx["workspace"]
    project = get_project_or_404(db, project_id, workspace.id)

    project.planning_draft = payload.model_dump()
    db.commit()
    db.refresh(project)

    return PlanningDraftSchema(**project.planning_draft)


@router.post("/projects/{project_id}/planning-draft/approve")
def approve_planning_draft(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    import datetime
    from src.db.models import DetailPageVersion, ImageGenerationJobRecord
    from src.services.image_generation_service import execute_image_generation, sync_job_to_project_json

    workspace = auth_ctx["workspace"]
    project = get_project_or_404(db, project_id, workspace.id)

    if not project.planning_draft:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="승인할 상세페이지 기획안이 없습니다.",
        )

    cards = project.planning_draft.get("cards") or []
    enabled_cards = [card for card in cards if card.get("is_enabled", True)]
    enabled_cards.sort(key=lambda card: card.get("sort_order", 0))

    # 기존 상세페이지와 이미지 생성 job을 교체해 중복 생성을 막는다.
    db.query(ProductPage).filter(ProductPage.project_id == project_id).delete()
    db.query(ImageGenerationJobRecord).filter(ImageGenerationJobRecord.project_id == project_id).delete()
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
    identity_preserving_card_types = {
        "hero",
        "lifestyle_scene",
        "lifestyle",
        "detail_1",
        "detail_2",
        "features",
        "cta",
    }

    for idx, card in enumerate(enabled_cards):
        visual_strategy = card.get("visual_strategy") or "text_only"
        card_type = card.get("type") or ""
        if card_type in {"specifications", "comparison", "pre_purchase", "product_information"}:
            needs_image = False
            visual_kind = "html_graphic"
        else:
            needs_image = visual_strategy in {"image_overlay", "lifestyle_image", "graphic_chart"}
            visual_kind = "image" if needs_image else "html_graphic"
        body_copy = "\n".join(card.get("bullets") or [])

        section = PageSection(
            page_id=page.id,
            section_type=card_type or f"section_{idx + 1}",
            title=card.get("title") or "",
            body_copy=body_copy,
            associated_fact_ids=card.get("source_fact_ids") or [],
            image_asset_id=None,
            visual_kind=visual_kind,
            visual_payload={"strategy": visual_strategy},
            sort_order=idx,
            is_visible=True,
        )
        db.add(section)
        db.flush()

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
            "image_asset_id": None,
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
