import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.auth import get_current_user_and_workspace
from src.db.database import get_db
from src.db.models import AgentRun, AgentRunStep, Brand, ProductProject
from src.services.intake_structuring_service import structure_intake
from src.services.url_evidence_collector import collect_url_evidence
from src.services.generation_status_service import GenerationStatusService


router = APIRouter(prefix="/agent-runs", tags=["agent-runs"])


def _extract_url_image_text(image_url: str) -> str:
    from src.config import settings

    if not settings.SELLFORM_URL_OCR_ENABLED:
        return ""
    try:
        from src.services.ai_adapter import OpenAIAdapter

        response = OpenAIAdapter().extract_facts(
            raw_text="이미지에서 확인되는 상품명, 라벨, 스펙만 추출하세요.",
            image_urls=[image_url],
        )
        return "\n".join(fact.fact_text for fact in response.data.facts)
    except Exception:
        return ""


# Pydantic Schemas
class ProductInputSchema(BaseModel):
    product_name: str = ""
    description: Optional[str] = None
    product_url: Optional[str] = None
    freeform_input: Optional[str] = None
    asset_ids: List[str] = Field(default_factory=list)
    reference_urls: List[str] = Field(default_factory=list, max_length=3)
    selling_points: List[str] = Field(default_factory=list)
    price: Optional[str] = None
    shipping: Optional[str] = None
    desired_mood: List[str] = Field(default_factory=list)


class AgentRunCreateRequest(BaseModel):
    product_name: str = ""
    description: Optional[str] = None
    product_url: Optional[str] = None
    freeform_input: Optional[str] = None
    asset_ids: List[str] = Field(default_factory=list)
    reference_urls: List[str] = Field(default_factory=list, max_length=3)
    selling_points: List[str] = Field(default_factory=list)
    price: Optional[str] = None
    shipping: Optional[str] = None
    desired_mood: List[str] = Field(default_factory=list)
    planning_mode: Optional[str] = "quality"


class AgentRunResponseSchema(BaseModel):
    id: str
    project_id: str
    workspace_id: str
    mode: str
    current_stage: str
    product_input: ProductInputSchema
    outputs: Dict[str, Any] = {}
    planning_mode: Optional[str] = "quality"


class AgentRunProgressStepSchema(BaseModel):
    stage: str
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class AgentRunProgressSchema(BaseModel):
    id: str
    status: str
    current_stage: str
    completed_stages: List[str]
    failed_stage: Optional[str] = None
    error_message: Optional[str] = None
    steps: List[AgentRunProgressStepSchema]


AGENT_STAGE_ORDER = [
    "input_router",
    "source_collection",
    "product_understanding",
    "reference_analysis",
    "sales_strategy",
    "page_planning",
    "copywriting",
    "visual_planning",
    "image_generation",
    "page_assembly",
    "qa_review",
]


@router.post("/structure-intake")
def structure_agent_intake(payload: dict):
    return structure_intake(payload)


@router.get("/{id}/status", response_model=AgentRunProgressSchema)
def get_agent_run_status(
    id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    workspace = auth_ctx["workspace"]
    run = (
        db.query(AgentRun)
        .filter(AgentRun.id == id, AgentRun.workspace_id == workspace.id)
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail=f"AgentRun not found: {id}")

    stage_rank = {stage: index for index, stage in enumerate(AGENT_STAGE_ORDER)}
    steps = (
        db.query(AgentRunStep)
        .filter(AgentRunStep.run_id == run.id)
        .all()
    )
    steps.sort(key=lambda step: stage_rank.get(step.stage, len(stage_rank)))
    failed_step = next((step for step in steps if step.status == "failed"), None)

    return AgentRunProgressSchema(
        id=run.id,
        status=run.status,
        current_stage=run.current_stage,
        completed_stages=[
            step.stage
            for step in steps
            if step.status == "completed"
        ],
        failed_stage=failed_step.stage if failed_step else None,
        error_message=failed_step.error_message if failed_step else None,
        steps=[
            AgentRunProgressStepSchema(
                stage=step.stage,
                status=step.status,
                started_at=step.started_at,
                completed_at=step.completed_at,
                error_message=step.error_message,
            )
            for step in steps
        ],
    )



def _normalize_product_name(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def _find_active_project_by_name(db: Session, workspace_id: str, product_name: str) -> ProductProject | None:
    normalized = _normalize_product_name(product_name)
    if not normalized:
        return None
    projects = (
        db.query(ProductProject)
        .filter(ProductProject.workspace_id == workspace_id)
        .order_by(ProductProject.updated_at.desc())
        .all()
    )
    for project in projects:
        if _normalize_product_name(project.name) == normalized:
            status_payload = GenerationStatusService(db).get_project_status(project.id, workspace_id)
            if status_payload["state"] in {"created", "running", "waiting_for_cost_approval", "needs_review"}:
                return project
    return None


@router.post("", response_model=AgentRunResponseSchema, status_code=201)
def create_agent_run(
    req: AgentRunCreateRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    user = auth_ctx["user"]
    workspace = auth_ctx["workspace"]
    collected_images: list[dict[str, str]] = []
    collected_specs: list[dict[str, str]] = []
    collected_text: list[str] = []
    collection_warnings: list[str] = []
    collected_product_name = ""

    for source_role, source_url in [
        ("product", req.product_url),
        *(("reference", url) for url in req.reference_urls),
    ]:
        if not source_url:
            continue
        try:
            evidence = collect_url_evidence(
                source_url,
                ocr_image=_extract_url_image_text,
            )
            if source_role == "product":
                collected_product_name = evidence.title
            collected_images.extend(
                {
                    "url": image_url,
                    "filename": image_url.rsplit("/", 1)[-1] or "url-image",
                    "source_type": "url-extracted",
                    "source_role": source_role,
                    "source_url": source_url,
                }
                for image_url in evidence.image_urls
            )
            collected_specs.extend(evidence.specs)
            collected_text.extend(
                [
                    *([evidence.description] if evidence.description else []),
                    *evidence.text_blocks,
                    *evidence.ocr_text_blocks,
                ]
            )
        except Exception as exc:
            collection_warnings.append(f"{source_url}: {exc}")

    resolved_product_name = req.product_name or collected_product_name

    # Duplicate run guard: block if same product name has an active project
    active_project = _find_active_project_by_name(db, workspace.id, resolved_product_name)
    if active_project is not None:
        status_payload = GenerationStatusService(db).get_project_status(active_project.id, workspace.id)
        active_run = status_payload.get("active_run") or {}
        raise HTTPException(
            status_code=409,
            detail={
                "code": "generation_already_running",
                "message": "이미 이 상품의 상세페이지 생성이 진행 중입니다.",
                "project_id": active_project.id,
                "run_id": active_run.get("id"),
                "state": status_payload["state"],
                "status_url": f"/workspace/operations?projectId={active_project.id}",
                "result_url": status_payload.get("result_url"),
            },
        )

    # 1. Fetch or create a default Brand for project creation
    brand = db.query(Brand).filter(Brand.workspace_id == workspace.id).first()
    if not brand:
        brand = Brand(
            workspace_id=workspace.id,
            name="Default Brand",
            font_tone="modern",
        )
        db.add(brand)
        db.commit()
        db.refresh(brand)

    # 2. Create ProductProject
    project = ProductProject(
        workspace_id=workspace.id,
        brand_id=brand.id,
        name=resolved_product_name or req.freeform_input or "Untitled product",
        raw_input_text=req.description or req.freeform_input or "\n".join(collected_text),
        raw_input_url=req.product_url,
        status="draft",
        current_step="raw_input",
        planning_mode=req.planning_mode or "quality",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    # 3. Create AgentRun
    run_id = str(uuid.uuid4())
    run = AgentRun(
        id=run_id,
        workspace_id=workspace.id,
        project_id=project.id,
        mode="mock",
        status="created",
        current_stage="intake",
        input_snapshot={
            "product_name": resolved_product_name,
            "description": req.description,
            "product_url": req.product_url,
            "freeform_input": req.freeform_input,
            "asset_ids": req.asset_ids,
            "reference_urls": req.reference_urls,
            "selling_points": req.selling_points,
            "price": req.price,
            "shipping": req.shipping,
            "desired_mood": req.desired_mood,
            "url_images": collected_images,
            "url_specs": collected_specs,
            "reference_text_blocks": collected_text,
            "source_collection_warnings": collection_warnings,
        },
        outputs_json={},
        cost_approval_status="not_required",
        created_by=user.id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    return AgentRunResponseSchema(
        id=run.id,
        project_id=project.id,
        workspace_id=workspace.id,
        mode=run.mode,
        current_stage=run.current_stage,
        product_input=ProductInputSchema(
            product_name=resolved_product_name,
            description=req.description,
            product_url=req.product_url,
            freeform_input=req.freeform_input,
            asset_ids=req.asset_ids,
            reference_urls=req.reference_urls,
            selling_points=req.selling_points,
            price=req.price,
            shipping=req.shipping,
            desired_mood=req.desired_mood,
        ),
        planning_mode=project.planning_mode,
    )


@router.post("/{id}/run-mock", response_model=AgentRunResponseSchema)
def run_mock(
    id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    from src.services.agent_run_service import AgentRunService
    workspace = auth_ctx["workspace"]

    try:
        run = AgentRunService.run_mock(id, workspace.id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return AgentRunResponseSchema(
        id=run.id,
        project_id=run.project_id,
        workspace_id=run.workspace_id,
        mode=run.mode,
        current_stage=run.current_stage,
        product_input=ProductInputSchema(
            product_name=run.input_snapshot.get("product_name") or "",
            description=run.input_snapshot.get("description"),
            product_url=run.input_snapshot.get("product_url"),
            freeform_input=run.input_snapshot.get("freeform_input"),
            asset_ids=run.input_snapshot.get("asset_ids") or [],
            reference_urls=run.input_snapshot.get("reference_urls") or [],
        ),
        outputs=run.outputs_json,
        planning_mode=run.project.planning_mode if run.project else "quality",
    )


@router.post("/{id}/run", response_model=AgentRunResponseSchema)
def run_real(
    id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    from src.services.agent_run_service import AgentRunService
    workspace = auth_ctx["workspace"]

    try:
        run = AgentRunService.run_real_text(id, workspace.id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return AgentRunResponseSchema(
        id=run.id,
        project_id=run.project_id,
        workspace_id=run.workspace_id,
        mode=run.mode,
        current_stage=run.current_stage,
        product_input=ProductInputSchema(
            product_name=run.input_snapshot.get("product_name") or "",
            description=run.input_snapshot.get("description"),
            product_url=run.input_snapshot.get("product_url"),
            freeform_input=run.input_snapshot.get("freeform_input"),
            asset_ids=run.input_snapshot.get("asset_ids") or [],
            reference_urls=run.input_snapshot.get("reference_urls") or [],
        ),
        outputs=run.outputs_json,
        planning_mode=run.project.planning_mode if run.project else "quality",
    )
