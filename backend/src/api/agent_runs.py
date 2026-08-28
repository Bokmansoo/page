import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.auth import get_current_user_and_workspace
from src.db.database import get_db
from src.db.models import AgentRun, AgentRunStep, Asset, Brand, ProductProject, SourceCapture
from src.services.intake_structuring_service import structure_intake
from src.services.url_evidence_collector import collect_url_evidence
from src.services.generation_status_service import GenerationStatusService
from src.services.seller_fact_ingestion_service import persist_confirmed_seller_specs
from src.agents.langgraph_runtime import configured_graph_runtime
from src.services.brand_kit_service import snapshot_project_brand_kit
from src.config import settings


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


def _image_mime_type_from_url(image_url: str) -> str:
    suffix = urlparse(image_url).path.rsplit(".", 1)[-1].lower() if "." in urlparse(image_url).path else ""
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "gif": "image/gif",
    }.get(suffix, "image/jpeg")


def _platform_from_url(source_url: str) -> str:
    host = (urlparse(source_url).hostname or "").lower().removeprefix("www.")
    for key, label in (
        ("1688.com", "1688"),
        ("coupang.com", "coupang"),
        ("xiaohongshu.com", "xiaohongshu"),
        ("xhslink.com", "xiaohongshu"),
        ("smartstore.naver.com", "naver_smartstore"),
    ):
        if host == key or host.endswith(f".{key}"):
            return label
    return host or "unknown"


def _collection_failure_code(error: Exception) -> str:
    message = str(error).lower()
    if "403" in message or "forbidden" in message:
        return "http_403"
    if "401" in message or "login" in message or "sign in" in message:
        return "login_required"
    if "captcha" in message or "verify you are human" in message:
        return "captcha_required"
    if "dynamic" in message or "javascript" in message:
        return "dynamic_page"
    if "timeout" in message:
        return "timeout"
    return "collection_failed"


def _asset_snapshot(assets: list[Asset], ordered_ids: list[str]) -> list[dict[str, Any]]:
    assets_by_id = {asset.id: asset for asset in assets}
    return [
        {
            "asset_id": asset.id,
            "order": index + 1,
            "filename": asset.filename,
            "mime_type": asset.mime_type,
            "file_size": asset.file_size,
            "source_type": asset.source_type,
            "usage_status": asset.usage_status,
        }
        for index, asset_id in enumerate(ordered_ids)
        if (asset := assets_by_id.get(asset_id)) is not None
    ]


def _persist_collected_url_images(
    db: Session,
    project_id: str,
    collected_images: list[dict[str, str]],
    ocr_text: str = "",
) -> list[dict[str, str]]:
    """Keep URL-derived product photos as project assets without generating a copy.

    The browser and export renderer can load an http(s) ``file_path`` directly.
    This preserves the original URL and gives the image a stable Asset id for page
    sections, candidates, and future provenance work.
    """
    persisted: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for image in collected_images:
        image_url = image.get("url") or ""
        if not image_url.startswith(("https://", "http://")) or image_url in seen_urls:
            continue
        seen_urls.add(image_url)
        filename = image.get("filename") or urlparse(image_url).path.rsplit("/", 1)[-1] or "url-image"
        asset = Asset(
            project_id=project_id,
            source_type="url-extracted",
            usage_status="reference_only",
            filename=filename[:255],
            file_path=image_url,
            mime_type=_image_mime_type_from_url(image_url),
            file_size=0,
            ocr_text=ocr_text or None,
        )
        db.add(asset)
        db.flush()
        persisted.append({
            **image,
            "asset_id": asset.id,
            "source_type": "url-extracted",
        })
    return persisted


# Pydantic Schemas
class ProductInputSchema(BaseModel):
    product_name: str = ""
    category: Optional[str] = None
    description: Optional[str] = None
    feature_details: Optional[str] = None
    components: Optional[str] = None
    cautions: Optional[str] = None
    product_url: Optional[str] = None
    freeform_input: Optional[str] = None
    asset_ids: List[str] = Field(default_factory=list)
    reference_urls: List[str] = Field(default_factory=list, max_length=3)
    selling_points: List[str] = Field(default_factory=list)
    price: Optional[str] = None
    shipping: Optional[str] = None
    sales_channel: Optional[str] = None
    model_options: Optional[str] = None
    desired_mood: List[str] = Field(default_factory=list)


class SourceCaptureSchema(BaseModel):
    url: str
    platform: str
    source_role: str
    collection_status: str
    failure_code: Optional[str] = None
    error_message: Optional[str] = None
    collected_image_count: int = 0
    collected_spec_count: int = 0


class AgentRunCreateRequest(BaseModel):
    product_name: str = ""
    category: Optional[str] = None
    description: Optional[str] = None
    feature_details: Optional[str] = None
    components: Optional[str] = None
    cautions: Optional[str] = None
    product_url: Optional[str] = None
    freeform_input: Optional[str] = None
    # Assets are attached only after the draft project exists. Accepting ids at
    # project creation would make ownership impossible to validate correctly.
    asset_ids: List[str] = Field(default_factory=list, max_length=0)
    reference_urls: List[str] = Field(default_factory=list, max_length=3)
    selling_points: List[str] = Field(default_factory=list)
    price: Optional[str] = None
    shipping: Optional[str] = None
    sales_channel: Optional[str] = None
    model_options: Optional[str] = None
    desired_mood: List[str] = Field(default_factory=list)
    # Browser intake explicitly sends the recommended `quick` mode. Missing
    # values belong to pre-LG-7/API clients and preserve the manual gate flow.
    planning_mode: Optional[str] = "expert"
    # The normal UX-1 route uses the automatic pipeline. Explicit advanced
    # review routes retain the existing evidence gates.
    ux_auto_generate: bool = False
    force_new: bool = False


class AgentRunResponseSchema(BaseModel):
    id: str
    project_id: str
    workspace_id: str
    mode: str
    current_stage: str
    product_input: ProductInputSchema
    outputs: Dict[str, Any] = Field(default_factory=dict)
    planning_mode: Optional[str] = "expert"
    collection_warnings: List[str] = Field(default_factory=list)
    source_captures: List[SourceCaptureSchema] = Field(default_factory=list)
    input_guidance: List[str] = Field(default_factory=list)
    graph_runtime: str = "legacy"


def _capture_schema(capture: SourceCapture | dict[str, Any]) -> SourceCaptureSchema:
    if isinstance(capture, dict):
        return SourceCaptureSchema(**capture)
    return SourceCaptureSchema(
        url=capture.url,
        platform=capture.platform,
        source_role=capture.source_role,
        collection_status=capture.collection_status,
        failure_code=capture.failure_code,
        error_message=capture.error_message,
        collected_image_count=capture.collected_image_count,
        collected_spec_count=capture.collected_spec_count,
    )


def _input_guidance(captures: list[SourceCapture | dict[str, Any]]) -> list[str]:
    if any(
        (item.get("collection_status") if isinstance(item, dict) else item.collection_status)
        in {"access_limited", "failed"}
        for item in captures
    ):
        return ["링크 자료를 모두 가져오지 못했습니다. 대표 사진과 기능·사용 장면·구성품 사진을 직접 올려 계속 진행할 수 있습니다."]
    return []


class AgentRunInputAssetsRequest(BaseModel):
    """Ordered seller image assets selected during the Sprint 1 intake flow."""

    asset_ids: List[str] = Field(default_factory=list, max_length=20)


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
    "category_classifier",
    "prompt_pack_resolver",
    "creative_brief_compiler",
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
    collected_ocr_text: list[str] = []
    collection_warnings: list[str] = []
    source_capture_attempts: list[dict[str, Any]] = []
    collected_product_name = ""

    for source_role, source_url in [
        ("product", req.product_url),
        *(("reference", url) for url in req.reference_urls),
    ]:
        if not source_url:
            continue
        capture = {
            "url": source_url,
            "platform": _platform_from_url(source_url),
            "source_role": source_role,
            "collection_status": "pending",
            "failure_code": None,
            "error_message": None,
            "collected_image_count": 0,
            "collected_spec_count": 0,
        }
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
            collected_ocr_text.extend(evidence.ocr_text_blocks)
            image_count = len(evidence.image_urls)
            spec_count = len(evidence.specs)
            # A marketplace can return a login shell or anti-bot placeholder
            # with HTTP 200.  It is not a successful collection when no
            # structured product evidence was actually obtained.
            if image_count == 0 and spec_count == 0:
                capture.update(
                    collection_status="access_limited",
                    failure_code="no_extractable_evidence",
                    error_message="상품 이미지나 스펙을 수집하지 못했습니다. 직접 업로드한 자료로 계속 진행할 수 있습니다.",
                )
                collection_warnings.append(
                    f"{source_url}: no extractable product images or specifications"
                )
            else:
                capture.update(
                    collection_status="collected",
                    collected_image_count=image_count,
                    collected_spec_count=spec_count,
                )
        except Exception as exc:
            failure_code = _collection_failure_code(exc)
            capture.update(
                collection_status="access_limited" if failure_code in {"http_403", "login_required", "captcha_required", "dynamic_page"} else "failed",
                failure_code=failure_code,
                error_message=str(exc)[:1000],
            )
            collection_warnings.append(f"{source_url}: {exc}")
        source_capture_attempts.append(capture)

    project_id = str(uuid.uuid4())
    from src.services.commerce_content_quality_service import normalize_product_name
    resolved_product_name, name_warnings = normalize_product_name(
        req.product_name or collected_product_name,
        fallback_id=project_id,
    )

    # Duplicate run guard: block by default, but allow the seller to intentionally
    # create a new version of the same product page.
    active_project = None
    if not req.force_new:
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
                "review_url": status_payload.get("review_url"),
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
        id=project_id,
        workspace_id=workspace.id,
        brand_id=brand.id,
        name=resolved_product_name,
        raw_input_text=req.description or req.freeform_input or "\n".join(collected_text),
        raw_input_url=req.product_url,
        status="draft",
        current_step="raw_input",
        category=req.category,
        category_confirmed=bool(req.category),
        category_confirmed_by=user.id if req.category else None,
        category_confirmed_at=datetime.utcnow() if req.category else None,
        planning_mode="expert" if (req.planning_mode or "expert") in {"expert", "quality"} else "quick",
        intake_snapshot={
            "input_bundle": {
                "product_name": resolved_product_name,
                "product_name_warnings": name_warnings,
                "category": req.category,
                "description": req.description,
                "feature_details": req.feature_details,
                "components": req.components,
                "cautions": req.cautions,
                "price": req.price,
                "shipping": req.shipping,
                "sales_channel": req.sales_channel,
                "model_options": req.model_options,
                "product_url": req.product_url,
                "reference_urls": req.reference_urls,
                "asset_ids": list(req.asset_ids or []),
                "asset_records": [],
                "source_captures": source_capture_attempts,
            }
        },
    )
    db.add(project)
    db.flush()
    snapshot_project_brand_kit(db, project)
    db.commit()
    db.refresh(project)

    for capture in source_capture_attempts:
        db.add(SourceCapture(project_id=project.id, **capture))
    db.commit()

    # Numeric specifications entered directly by the seller are first-party
    # facts. Persist them before generation so Sprint 4 can build grounded
    # spec tables and numeric highlights even when no LLM extraction is used.
    persist_confirmed_seller_specs(
        db,
        project.id,
        [
            req.description,
            req.feature_details,
            req.components,
            req.cautions,
            req.freeform_input,
            *(req.selling_points or []),
        ],
    )
    db.commit()

    # Preserve URL-collected product photos as first-class assets. They are later
    # preferred after uploads and can be linked to a page section by id.
    collected_images = _persist_collected_url_images(
        db,
        project.id,
        collected_images,
        ocr_text="\n".join(collected_ocr_text),
    )
    db.commit()
    input_asset_ids = list(
        dict.fromkeys([*(req.asset_ids or []), *(image["asset_id"] for image in collected_images)])
    )
    if input_asset_ids:
        assets = db.query(Asset).filter(Asset.project_id == project.id, Asset.id.in_(input_asset_ids)).all()
        intake_snapshot = dict(project.intake_snapshot or {})
        input_bundle = dict(intake_snapshot.get("input_bundle") or {})
        input_bundle["asset_ids"] = input_asset_ids
        input_bundle["asset_records"] = _asset_snapshot(assets, input_asset_ids)
        intake_snapshot["input_bundle"] = input_bundle
        project.intake_snapshot = intake_snapshot
        db.commit()

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
            "category": req.category,
            "description": req.description,
            "feature_details": req.feature_details,
            "components": req.components,
            "cautions": req.cautions,
            "product_url": req.product_url,
            "freeform_input": req.freeform_input,
            "asset_ids": input_asset_ids,
            "reference_urls": req.reference_urls,
            "selling_points": req.selling_points,
            "price": req.price,
            "shipping": req.shipping,
            "sales_channel": req.sales_channel,
            "model_options": req.model_options,
            "desired_mood": req.desired_mood,
            "url_images": collected_images,
            "url_specs": collected_specs,
            "reference_text_blocks": collected_text,
            "source_collection_warnings": collection_warnings,
            "ux_auto_generate": req.ux_auto_generate,
            "interaction_mode": "expert" if (req.planning_mode or "expert") in {"expert", "quality"} else "quick",
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
            category=req.category,
            description=req.description,
            feature_details=req.feature_details,
            components=req.components,
            cautions=req.cautions,
            product_url=req.product_url,
            freeform_input=req.freeform_input,
            asset_ids=input_asset_ids,
            reference_urls=req.reference_urls,
            selling_points=req.selling_points,
            price=req.price,
            shipping=req.shipping,
            sales_channel=req.sales_channel,
            model_options=req.model_options,
            desired_mood=req.desired_mood,
        ),
        planning_mode=project.planning_mode,
        collection_warnings=collection_warnings,
        source_captures=[_capture_schema(capture) for capture in source_capture_attempts],
        input_guidance=_input_guidance(source_capture_attempts),
        graph_runtime=configured_graph_runtime(),
    )


@router.patch("/{id}/input-assets", response_model=AgentRunResponseSchema)
def update_agent_run_input_assets(
    id: str,
    req: AgentRunInputAssetsRequest,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    """Persist the seller's image order before any agent stage is executed."""
    workspace = auth_ctx["workspace"]
    run = (
        db.query(AgentRun)
        .filter(AgentRun.id == id, AgentRun.workspace_id == workspace.id)
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="AgentRun not found")

    project = db.query(ProductProject).filter(ProductProject.id == run.project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    existing_intake_snapshot = dict(project.intake_snapshot or {})
    if existing_intake_snapshot.get("input_bundle_locked"):
        raise HTTPException(
            status_code=409,
            detail="The product input bundle is already confirmed. Create a new run to change image order.",
        )

    ordered_ids = list(dict.fromkeys(req.asset_ids))
    if not ordered_ids:
        raise HTTPException(
            status_code=422,
            detail="A representative product image is required before confirming the input bundle.",
        )
    assets = db.query(Asset).filter(Asset.project_id == run.project_id, Asset.id.in_(ordered_ids)).all()
    if len(assets) != len(ordered_ids) or any(not asset.mime_type.startswith("image/") for asset in assets):
        raise HTTPException(status_code=422, detail="asset_ids must be image assets from this project")

    input_snapshot = run.input_snapshot or {}
    if not str(input_snapshot.get("product_name") or "").strip() and not str(input_snapshot.get("product_url") or "").strip():
        raise HTTPException(status_code=422, detail="A product name or product URL is required.")
    seller_core_fields = [
        input_snapshot.get("description"),
        input_snapshot.get("feature_details"),
        input_snapshot.get("components"),
        input_snapshot.get("cautions"),
        input_snapshot.get("freeform_input"),
        *(input_snapshot.get("selling_points") or []),
    ]
    if not any(str(value or "").strip() for value in seller_core_fields):
        raise HTTPException(
            status_code=422,
            detail="At least one seller-confirmed product fact is required before confirming the input bundle.",
        )

    assets_by_id = {asset.id: asset for asset in assets}
    for index, asset_id in enumerate(ordered_ids, start=1):
        assets_by_id[asset_id].intake_order = index

    snapshot = dict(run.input_snapshot or {})
    snapshot["asset_ids"] = ordered_ids
    snapshot["asset_records"] = _asset_snapshot(assets, ordered_ids)
    run.input_snapshot = snapshot
    input_bundle = dict(existing_intake_snapshot.get("input_bundle") or {})
    input_bundle["asset_ids"] = ordered_ids
    input_bundle["asset_records"] = _asset_snapshot(assets, ordered_ids)
    input_bundle["confirmed_at"] = datetime.utcnow().isoformat()
    existing_intake_snapshot["input_bundle"] = input_bundle
    existing_intake_snapshot["input_bundle_locked"] = True
    project.intake_snapshot = existing_intake_snapshot
    db.commit()
    db.refresh(run)
    source_captures = db.query(SourceCapture).filter(SourceCapture.project_id == run.project_id).all()

    return AgentRunResponseSchema(
        id=run.id,
        project_id=run.project_id,
        workspace_id=run.workspace_id,
        mode=run.mode,
        current_stage=run.current_stage,
        product_input=ProductInputSchema(
            product_name=run.input_snapshot.get("product_name") or "",
            category=run.input_snapshot.get("category"),
            description=run.input_snapshot.get("description"),
            feature_details=run.input_snapshot.get("feature_details"),
            components=run.input_snapshot.get("components"),
            cautions=run.input_snapshot.get("cautions"),
            product_url=run.input_snapshot.get("product_url"),
            freeform_input=run.input_snapshot.get("freeform_input"),
            asset_ids=run.input_snapshot.get("asset_ids") or [],
            reference_urls=run.input_snapshot.get("reference_urls") or [],
            selling_points=run.input_snapshot.get("selling_points") or [],
            price=run.input_snapshot.get("price"),
            shipping=run.input_snapshot.get("shipping"),
            sales_channel=run.input_snapshot.get("sales_channel"),
            model_options=run.input_snapshot.get("model_options"),
            desired_mood=run.input_snapshot.get("desired_mood") or [],
        ),
        outputs=run.outputs_json or {},
        planning_mode=run.project.planning_mode if run.project else "quality",
        collection_warnings=run.input_snapshot.get("source_collection_warnings") or [],
        source_captures=[_capture_schema(capture) for capture in source_captures],
        input_guidance=_input_guidance(source_captures),
    )


@router.post("/{id}/run-mock", response_model=AgentRunResponseSchema)
def run_mock(
    id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    if settings.SELLFORM_GRAPH_RUNTIME == "langgraph":
        raise HTTPException(
            status_code=410,
            detail={"code": "legacy_generation_writer_disabled", "message": "Use the unified graph-run intake."},
        )
    from src.services.agent_run_service import (
        AgentRunService,
        AssetUnderstandingNotReady,
        FactEvidenceNotReady,
    )
    workspace = auth_ctx["workspace"]

    try:
        run = AgentRunService.run_mock(id, workspace.id, db)
    except AssetUnderstandingNotReady as e:
        raise HTTPException(
            status_code=409,
            detail={"code": "asset_understanding_not_ready", "blockers": e.blockers},
        )
    except FactEvidenceNotReady as e:
        target_run = db.query(AgentRun).filter(AgentRun.id == id).first()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "fact_evidence_not_ready",
                "message": "사실·증거 확인을 완료한 뒤 상세페이지 생성을 다시 실행해 주세요.",
                "blockers": e.blockers,
                "review_url": f"/workspace/projects/{target_run.project_id}/facts" if target_run else None,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    source_captures = db.query(SourceCapture).filter(SourceCapture.project_id == run.project_id).all()
    return AgentRunResponseSchema(
        id=run.id,
        project_id=run.project_id,
        workspace_id=run.workspace_id,
        mode=run.mode,
        current_stage=run.current_stage,
        product_input=ProductInputSchema(
            product_name=run.input_snapshot.get("product_name") or "",
            category=run.input_snapshot.get("category"),
            description=run.input_snapshot.get("description"),
            feature_details=run.input_snapshot.get("feature_details"),
            components=run.input_snapshot.get("components"),
            cautions=run.input_snapshot.get("cautions"),
            product_url=run.input_snapshot.get("product_url"),
            freeform_input=run.input_snapshot.get("freeform_input"),
            asset_ids=run.input_snapshot.get("asset_ids") or [],
            reference_urls=run.input_snapshot.get("reference_urls") or [],
            sales_channel=run.input_snapshot.get("sales_channel"),
            model_options=run.input_snapshot.get("model_options"),
        ),
        outputs=run.outputs_json,
        planning_mode=run.project.planning_mode if run.project else "quality",
        collection_warnings=run.input_snapshot.get("source_collection_warnings") or [],
        source_captures=[_capture_schema(capture) for capture in source_captures],
        input_guidance=_input_guidance(source_captures),
    )


@router.post("/{id}/run", response_model=AgentRunResponseSchema)
def run_real(
    id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    if settings.SELLFORM_GRAPH_RUNTIME == "langgraph":
        raise HTTPException(
            status_code=410,
            detail={"code": "legacy_generation_writer_disabled", "message": "Use the unified graph-run intake."},
        )
    from src.services.agent_run_service import (
        AgentRunService,
        AssetUnderstandingNotReady,
        FactEvidenceNotReady,
    )
    workspace = auth_ctx["workspace"]

    try:
        run = AgentRunService.run_real_text(id, workspace.id, db)
    except AssetUnderstandingNotReady as e:
        raise HTTPException(
            status_code=409,
            detail={"code": "asset_understanding_not_ready", "blockers": e.blockers},
        )
    except FactEvidenceNotReady as e:
        target_run = db.query(AgentRun).filter(AgentRun.id == id).first()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "fact_evidence_not_ready",
                "message": "사실·증거 확인을 완료한 뒤 상세페이지 생성을 다시 실행해 주세요.",
                "blockers": e.blockers,
                "review_url": f"/workspace/projects/{target_run.project_id}/facts" if target_run else None,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    source_captures = db.query(SourceCapture).filter(SourceCapture.project_id == run.project_id).all()
    return AgentRunResponseSchema(
        id=run.id,
        project_id=run.project_id,
        workspace_id=run.workspace_id,
        mode=run.mode,
        current_stage=run.current_stage,
        product_input=ProductInputSchema(
            product_name=run.input_snapshot.get("product_name") or "",
            category=run.input_snapshot.get("category"),
            description=run.input_snapshot.get("description"),
            feature_details=run.input_snapshot.get("feature_details"),
            components=run.input_snapshot.get("components"),
            cautions=run.input_snapshot.get("cautions"),
            product_url=run.input_snapshot.get("product_url"),
            freeform_input=run.input_snapshot.get("freeform_input"),
            asset_ids=run.input_snapshot.get("asset_ids") or [],
            reference_urls=run.input_snapshot.get("reference_urls") or [],
            sales_channel=run.input_snapshot.get("sales_channel"),
            model_options=run.input_snapshot.get("model_options"),
        ),
        outputs=run.outputs_json,
        planning_mode=run.project.planning_mode if run.project else "quality",
        collection_warnings=run.input_snapshot.get("source_collection_warnings") or [],
        source_captures=[_capture_schema(capture) for capture in source_captures],
        input_guidance=_input_guidance(source_captures),
    )
