import os
import uuid
import logging
import datetime
import hashlib
import json
import time
from typing import Optional, List, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import flag_modified
from src.config import settings
from src.db.models import AgentRun, ProductProject, Asset, ImageGenerationJobRecord, ImageGenerationOutboxRecord, ImageGenerationProviderAttemptRecord
from src.services.image_generation_provider import ImageGenerationRequest, ImageGenerationResult
from src.services.commerce_content_quality_service import auto_placement_risk_codes
from src.services.generation_provider_adapter import get_image_generation_adapter
from src.services.image_asset_inspector import inspect_asset
from src.services.product_identity_validator import ProductIdentityValidator, ProductIdentityValidationError

logger = logging.getLogger(__name__)
RETRYABLE_PROVIDER_ERRORS = {"RATE_LIMIT_EXCEEDED", "TIMEOUT"}
_PERSISTED_PROVIDER_ERROR_CODES = {
    "API_KEY_MISSING",
    "BALANCE_OR_LIMIT",
    "BILLING_HARD_LIMIT_REACHED",
    "FILE_SAVE_ERROR",
    "IDENTITY_MISMATCH",
    "INVALID_REQUEST",
    "MODERATION_REJECTED",
    "OCR_CONTAMINATION",
    "PRE_DISPATCH_FAILURE",
    "PROVIDER_ERROR",
    "PROVIDER_OUTCOME_UNKNOWN",
    "PROVIDER_RESULT_ERROR",
    "PROVIDER_SAFETY",
    "PROVIDER_TIMEOUT",
    "RATE_LIMIT_EXCEEDED",
    "RIGHTS_BLOCKED",
    "TIMEOUT",
    "UNSAFE_GENERATED_CONTENT_DETECTED",
}
_SAFE_PROVIDER_FAILURE_ACTION = "이미지 생성 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요."
LG9_VALIDATION_SCHEMA_VERSION = "lg9-image-validation-v1"
_COST_STATES = {"NOT_DISPATCHED", "EXPLICIT_ZERO", "KNOWN", "UNKNOWN_AFTER_DISPATCH"}
_USAGE_SCALARS = ("input_tokens", "output_tokens", "total_tokens", "input_images", "output_images")


def _record_provider_attempt(
    record: ImageGenerationJobRecord,
    *,
    status: str,
    error_code: str | None = None,
) -> None:
    """Persist a provider-neutral retry audit for a generation job."""
    metadata = dict(record.usage_metadata or {})
    history = list(metadata.get("attempt_history") or [])
    entry = {
        "attempt": record.attempt_count,
        "status": status,
        "provider": record.provider or settings.SELLFORM_IMAGE_PROVIDER,
        "model": record.model or settings.SELLFORM_IMAGE_MODEL,
    }
    if error_code:
        entry["error_code"] = error_code
    if history and history[-1].get("attempt") == record.attempt_count:
        history[-1] = {**history[-1], **entry}
    else:
        history.append(entry)
    metadata["attempt_history"] = history
    record.usage_metadata = metadata


def _split_provider_error(error: Exception) -> tuple[str, str]:
    """Return only a bounded provider code and seller-safe persisted action."""

    candidate = " ".join(str(error).split()).split(":", 1)[0].strip().upper()
    code = candidate if candidate in _PERSISTED_PROVIDER_ERROR_CODES else "PROVIDER_ERROR"
    return code, _SAFE_PROVIDER_FAILURE_ACTION


def _is_production_langgraph_job(record: ImageGenerationJobRecord) -> bool:
    """Keep LG-9 reporting on the production LangGraph execution path only."""

    return bool((record.usage_metadata or {}).get("langgraph_run_id"))


def _cost_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()


def _bounded_number(value: Any, *, integer: bool = False) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or value > 1_000_000_000:
        return None
    return int(value) if integer else float(value)


def normalize_provider_usage(metadata: Any) -> tuple[dict[str, Any], float | None, str]:
    """Retain only provider-neutral accounting scalars, never a raw response."""

    source = dict(metadata or {}) if isinstance(metadata, dict) else {}
    usage: dict[str, Any] = {}
    for name in _USAGE_SCALARS:
        value = _bounded_number(source.get(name), integer=True)
        if value is not None:
            usage[name] = value
    cost = _bounded_number(source.get("actual_cost", source.get("cost")))
    if cost is not None:
        usage["provider_reported_cost"] = cost
    currency = str(source.get("currency") or "credit").strip().lower()
    if not currency.isalpha() or len(currency) > 20:
        currency = "credit"
    usage["availability"] = "reported" if usage else "missing"
    return usage, cost, currency


def _provider_attempt_context(record: ImageGenerationJobRecord, db: Session) -> tuple[AgentRun, ImageGenerationOutboxRecord | None] | None:
    run_id = str((record.usage_metadata or {}).get("langgraph_run_id") or "")
    if not run_id:
        return None
    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    outbox = record.outbox_record
    # Historical unit/legacy callers mark a job as LangGraph-shaped without a
    # persisted run or outbox. They retain the old per-job behavior; the
    # production LG-5R worker always has the durable tuple below.
    if run is None and outbox is None:
        return None
    expected_thread = run.graph_thread_id or run.id if run is not None else ""
    if (
        run is None
        or run.project_id != record.project_id
        or (outbox is not None and (
            outbox.workspace_id != run.workspace_id
            or outbox.project_id != run.project_id
            or outbox.run_id != run.id
            or outbox.thread_id != expected_thread
            or outbox.image_job_id != record.id
            or outbox.job_id != record.job_id
        ))
    ):
        raise ValueError("Provider cost attempt scope does not match the persisted LangGraph work.")
    return run, outbox


def _provider_attempt_key(
    *, run: AgentRun, record: ImageGenerationJobRecord, outbox: ImageGenerationOutboxRecord | None,
    provider_adapter_attempt: int, provider: str, model: str,
) -> str:
    return _cost_hash({
        "run_id": run.id,
        "thread_id": run.graph_thread_id or run.id,
        "job_id": record.id,
        "job_key": record.idempotency_key,
        "seller_generation_attempt": int(record.generation_attempt or 1),
        "delivery_id": outbox.id if outbox else "",
        "delivery_attempt": int(outbox.delivery_attempts or 0) if outbox else 0,
        "provider_adapter_attempt": provider_adapter_attempt,
        "provider": provider,
        "model": model,
    })


def _project_provider_costs(run: AgentRun, db: Session) -> dict[str, Any]:
    rows = db.query(ImageGenerationProviderAttemptRecord).filter(
        ImageGenerationProviderAttemptRecord.run_id == run.id
    ).order_by(ImageGenerationProviderAttemptRecord.started_at.asc(), ImageGenerationProviderAttemptRecord.id.asc()).all()
    known = sum(float(row.actual_cost or 0) for row in rows if row.cost_state != "UNKNOWN_AFTER_DISPATCH")
    unknown = sum(row.cost_state == "UNKNOWN_AFTER_DISPATCH" for row in rows)
    by_job: dict[str, float] = {}
    for row in rows:
        if row.cost_state != "UNKNOWN_AFTER_DISPATCH":
            by_job[row.image_job_id] = by_job.get(row.image_job_id, 0.0) + float(row.actual_cost or 0)
    for job_id, actual_cost in by_job.items():
        job = db.query(ImageGenerationJobRecord).filter(ImageGenerationJobRecord.id == job_id).one_or_none()
        if job is not None:
            job.actual_cost = actual_cost
            db.add(job)
    summary = {
        "known_actual_cost": known,
        "has_unknown_cost": bool(unknown),
        "actual_cost_complete": not bool(unknown),
        "attempt_count": len(rows),
        "unknown_attempt_count": int(unknown),
    }
    return summary


def _append_provider_attempt(
    record: ImageGenerationJobRecord,
    db: Session,
    *,
    provider_adapter_attempt: int,
    provider: str,
    model: str,
    dispatch_state: str,
    cost_state: str,
    actual_cost: float | None,
    currency: str,
    usage: dict[str, Any],
    outcome_code: str,
    started_at: datetime.datetime,
    completed_at: datetime.datetime,
    latency_ms: int | None,
) -> ImageGenerationProviderAttemptRecord | None:
    if cost_state not in _COST_STATES:
        raise ValueError("Unsupported provider cost state.")
    context = _provider_attempt_context(record, db)
    if context is None:
        return None
    run, outbox = context
    key = _provider_attempt_key(
        run=run, record=record, outbox=outbox, provider_adapter_attempt=provider_adapter_attempt,
        provider=provider, model=model,
    )
    row = ImageGenerationProviderAttemptRecord(
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        run_id=run.id,
        thread_id=run.graph_thread_id or run.id,
        image_job_id=record.id,
        outbox_id=outbox.id if outbox else None,
        job_id=record.job_id,
        scene_id=record.scene_id or record.section_id,
        seller_generation_attempt=int(record.generation_attempt or 1),
        delivery_attempt=int(outbox.delivery_attempts or 0) if outbox else 0,
        provider_adapter_attempt=provider_adapter_attempt,
        provider=provider[:50],
        model=model[:100],
        semantic_idempotency_key=key,
        dispatch_state=dispatch_state,
        cost_state=cost_state,
        estimated_cost_at_dispatch=record.estimated_cost,
        actual_cost=actual_cost,
        currency=currency,
        usage_json=usage,
        outcome_code=outcome_code[:100],
        latency_ms=latency_ms,
        started_at=started_at,
        completed_at=completed_at,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        row = db.query(ImageGenerationProviderAttemptRecord).filter(
            ImageGenerationProviderAttemptRecord.semantic_idempotency_key == key
        ).one()
        return row
    _project_provider_costs(run, db)
    from src.services.langgraph_run_service import AgentRunEventJournal
    AgentRunEventJournal.append_provider_cost_event(run, db, ledger=row)
    return row


def record_unknown_provider_attempt_for_delivery(
    record: ImageGenerationJobRecord,
    db: Session,
    *,
    outcome_code: str = "PROVIDER_OUTCOME_UNKNOWN",
) -> ImageGenerationProviderAttemptRecord | None:
    """Record a conservative immutable cost fact for a paid recovery window."""

    context = _provider_attempt_context(record, db)
    if context is None:
        return None
    _run, outbox = context
    provider_attempt = max(int(record.attempt_count or 0), int(outbox.delivery_attempts or 0) if outbox else 0, 1)
    now = datetime.datetime.utcnow()
    return _append_provider_attempt(
        record, db,
        provider_adapter_attempt=provider_attempt,
        provider=str(record.provider or "unknown"),
        model=str(record.model or "unknown"),
        dispatch_state="DISPATCHED",
        cost_state="UNKNOWN_AFTER_DISPATCH",
        actual_cost=None,
        currency="credit",
        usage={"availability": "missing"},
        outcome_code=outcome_code,
        started_at=now,
        completed_at=now,
        latency_ms=None,
    )


def reconcile_provider_cost_projection(run_id: str, db: Session) -> bool:
    """Repair a result/ledger-to-projection crash window without provider work."""

    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    if run is None:
        return False
    rows = db.query(ImageGenerationProviderAttemptRecord).filter(
        ImageGenerationProviderAttemptRecord.run_id == run.id
    ).order_by(ImageGenerationProviderAttemptRecord.started_at.asc(), ImageGenerationProviderAttemptRecord.id.asc()).all()
    if not rows:
        return False
    _project_provider_costs(run, db)
    from src.services.langgraph_run_service import AgentRunEventJournal
    changed = False
    for row in rows:
        _event, appended, _locked = AgentRunEventJournal.append_provider_cost_event(run, db, ledger=row)
        changed = changed or appended
    return changed


def _scene_prompt_rights_status(record: ImageGenerationJobRecord) -> tuple[str, list[dict[str, Any]]]:
    """Evaluate the immutable LG-8 reference-rights snapshot for generation."""

    scene_prompt = dict((record.input_snapshot or {}).get("scene_prompt") or {})
    rights_snapshot = list(scene_prompt.get("rights_snapshot") or [])
    states = {str(item.get("rights_status") or "unverified") for item in rights_snapshot if isinstance(item, dict)}
    if "blocked" in states:
        return "blocked", rights_snapshot
    if not rights_snapshot or states.intersection({"unverified", "needs_review"}):
        return "needs_review", rights_snapshot
    return "passed", rights_snapshot


def _lg9_validation_report(
    record: ImageGenerationJobRecord,
    output_asset: Asset,
    db: Session,
    *,
    identity_warnings: list[str],
    identity_report: dict[str, Any] | None,
    ocr_text: str,
    ocr_source: str,
    risk_codes: list[str],
    revised_prompt: str | None,
) -> dict[str, Any]:
    """Aggregate existing deterministic checks for one generated scene candidate."""

    inspection = inspect_asset(output_asset, db)
    inspection_warnings = list(inspection.quality_warnings or [])
    resolution = "needs_review" if "LOW_RESOLUTION" in inspection_warnings else "passed"
    crop = "passed" if inspection.safe_crop_status == "safe" else "needs_review"
    ocr_unavailable = ocr_source in {
        "ocr_check_failed", "ocr_engine_not_configured", "ocr_image_not_available", "ocr_image_not_local",
    }
    ocr = "needs_review" if ocr_text or ocr_unavailable else "passed"
    rights, rights_snapshot = _scene_prompt_rights_status(record)
    identity_status = str((identity_report or {}).get("status") or (
        "needs_review" if identity_warnings else "passed"
    ))
    checks = {
        "identity": identity_status,
        "ocr": ocr,
        "crop": crop,
        "resolution": resolution,
        "safety": "blocked" if risk_codes else "passed",
        "rights": rights,
        # Preserve the fields consumed by the existing review payload.
        "image_quality": "passed",
        "supplier_text": ocr,
        "supplier_layout": "passed",
    }
    statuses = set(checks.values())
    status = "blocked" if "blocked" in statuses else "needs_review" if "needs_review" in statuses else "passed"
    return {
        "schema_version": LG9_VALIDATION_SCHEMA_VERSION,
        "status": status,
        "checks": checks,
        "warnings": [*identity_warnings, *inspection_warnings],
        "risk_codes": list(risk_codes),
        "ocr_source": ocr_source,
        "ocr_text": ocr_text[:500],
        "details": {
            "identity": identity_report or {
                "status": identity_status,
                "checks": {},
            },
            "crop": {"safe_crop_status": inspection.safe_crop_status},
            "resolution": {"width": inspection.width, "height": inspection.height},
            "rights_snapshot": rights_snapshot,
        },
        "revised_prompt": revised_prompt,
    }


def _lg9_pre_asset_failure_report(error: ProductIdentityValidationError) -> dict[str, Any]:
    reason = str(error)[:500]
    identity = "blocked" if "output rejected" in reason.lower() else "not_run"
    resolution = "blocked" if "dimension" in reason.lower() else "not_run"
    return {
        "schema_version": LG9_VALIDATION_SCHEMA_VERSION,
        "status": "blocked",
        "checks": {
            "identity": identity,
            "ocr": "not_run",
            "crop": "not_run",
            "resolution": resolution,
            "safety": "not_run",
            "rights": "not_run",
        },
        "warnings": [reason],
        "risk_codes": [],
    }


def get_or_create_job_record(project_id: str, job_id: str, db: Session) -> ImageGenerationJobRecord:
    # 1. Look up in table
    record = db.query(ImageGenerationJobRecord).filter(
        ImageGenerationJobRecord.project_id == project_id,
        ImageGenerationJobRecord.job_id == job_id
    ).first()

    if record:
        return record

    # 2. If not found in table, load from project.visual_package_jobs JSON list
    project = db.query(ProductProject).filter(ProductProject.id == project_id).first()
    if not project or not project.visual_package_jobs:
        raise ValueError(f"No planned visual package jobs found for project '{project_id}'")

    job_data = None
    for j in project.visual_package_jobs:
        if j.get("job_id") == job_id:
            job_data = j
            break

    if not job_data:
        raise ValueError(f"Job '{job_id}' not found in planned package for project '{project_id}'")

    # Create new ImageGenerationJobRecord
    record = ImageGenerationJobRecord(
        project_id=project_id,
        job_id=job_id,
        section_id=job_data.get("section_id"),
        role=job_data.get("role"),
        source_asset_ids=job_data.get("source_asset_ids", []),
        prompt=job_data.get("prompt"),
        negative_prompt=job_data.get("negative_prompt", ""),
        preserve_product_identity=job_data.get("preserve_product_identity", True),
        output_size=job_data.get("output_size", "1024x1024"),
        cost_tier=job_data.get("cost_tier", "standard"),
        status=job_data.get("status", "planned"),
        provider=settings.SELLFORM_IMAGE_PROVIDER,
        model=settings.SELLFORM_IMAGE_MODEL,
        attempt_count=job_data.get("attempt_count", 0),
        output_asset_id=job_data.get("output_asset_id"),
        error_code=job_data.get("error_code"),
        warnings=job_data.get("warnings")
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return record


def sync_job_to_project_json(project_id: str, job_id: str, db: Session) -> None:
    project = db.query(ProductProject).filter(ProductProject.id == project_id).first()
    if not project or not project.visual_package_jobs:
        return

    record = db.query(ImageGenerationJobRecord).filter(
        ImageGenerationJobRecord.project_id == project_id,
        ImageGenerationJobRecord.job_id == job_id
    ).first()
    if not record:
        return

    jobs = list(project.visual_package_jobs)
    job_idx = -1
    for idx, j in enumerate(jobs):
        if j.get("job_id") == job_id:
            job_idx = idx
            break

    if job_idx != -1:
        job_dict = dict(jobs[job_idx])
        job_dict["status"] = record.status
        job_dict["prompt"] = record.prompt
        job_dict["source_asset_ids"] = record.source_asset_ids
        job_dict["preserve_product_identity"] = record.preserve_product_identity
        job_dict["cost_tier"] = record.cost_tier
        job_dict["output_size"] = record.output_size
        job_dict["output_asset_id"] = record.output_asset_id
        job_dict["attempt_count"] = record.attempt_count
        job_dict["error_code"] = record.error_code
        job_dict["warnings"] = record.warnings
        job_dict["provider"] = record.provider
        job_dict["model"] = record.model
        jobs[job_idx] = job_dict
        project.visual_package_jobs = jobs
        flag_modified(project, "visual_package_jobs")
        db.commit()


def execute_image_generation(
    project_id: str,
    job_id: str,
    db: Session,
    cost_approved: bool = False,
    provider_override: Optional[Any] = None
) -> ImageGenerationJobRecord:
    # 1. Get or create job record
    record = get_or_create_job_record(project_id, job_id, db)
    is_production_langgraph = _is_production_langgraph_job(record)

    # 2. Idempotency check: if already generating/needs_review/approved, don't trigger new calls
    if record.status in ["generating", "needs_review", "approved"]:
        return record

    # 3. Validate source asset ownership
    if record.source_asset_ids:
        for asset_id in record.source_asset_ids:
            asset = db.query(Asset).filter(Asset.id == asset_id).first()
            if not asset or asset.project_id != project_id:
                raise ValueError(f"Source asset '{asset_id}' does not belong to project '{project_id}'")

    source_asset_paths = []
    if record.source_asset_ids:
        assets = db.query(Asset).filter(Asset.id.in_(record.source_asset_ids)).all()
        asset_map = {a.id: a for a in assets}
        for asset_id in record.source_asset_ids:
            asset = asset_map.get(asset_id)
            if not asset:
                raise ValueError(f"Source asset '{asset_id}' was not found")
            if not os.path.isfile(asset.file_path):
                raise ValueError(
                    f"Source asset file for '{asset_id}' does not exist: {asset.file_path}"
                )
            source_asset_paths.append(asset.file_path)

    # 4. Check cost approval gate
    if not cost_approved:
        if record.status != "awaiting_cost_approval":
            record.status = "awaiting_cost_approval"
            db.commit()
            sync_job_to_project_json(project_id, job_id, db)
        return record

    # 5. Set status to generating
    record.status = "generating"
    db.commit()
    sync_job_to_project_json(project_id, job_id, db)

    quality = "high" if record.cost_tier == "premium" else "medium"
    req = ImageGenerationRequest(
        job_id=job_id,
        role=record.role,
        prompt=record.prompt,
        negative_prompt=record.negative_prompt or "",
        source_asset_paths=source_asset_paths,
        preserve_product_identity=record.preserve_product_identity,
        size=record.output_size or "1024x1024",
        quality=quality,
        transparent_background=(record.role == "cutout_product"),
        reference_asset_ids=record.source_asset_ids or [],
        requires_cost_approval=True,
        cost_approved=cost_approved,
        product_identity_required=record.preserve_product_identity
    )

    provider = provider_override
    if not provider:
        try:
            if settings.SELLFORM_IMAGE_GENERATION_MODE == "real":
                provider = get_image_generation_adapter(record.provider or settings.SELLFORM_IMAGE_PROVIDER, record.model)
            else:
                from src.services.image_generation_provider import MockImageGenerationProvider
                provider = MockImageGenerationProvider()
        except Exception as error:
            record.attempt_count += 1
            now = datetime.datetime.utcnow()
            _append_provider_attempt(
                record,
                db,
                provider_adapter_attempt=record.attempt_count,
                provider=str(record.provider or settings.SELLFORM_IMAGE_PROVIDER),
                model=str(record.model or settings.SELLFORM_IMAGE_MODEL),
                dispatch_state="NOT_DISPATCHED",
                cost_state="NOT_DISPATCHED",
                actual_cost=0.0,
                currency="credit",
                usage={"availability": "missing"},
                outcome_code="PRE_DISPATCH_FAILURE",
                started_at=now,
                completed_at=now,
                latency_ms=0,
            )
            record.status = "failed"
            record.error_code = "PRE_DISPATCH_FAILURE"
            record.warnings = ["이미지 생성 준비를 완료하지 못했습니다."]
            _record_provider_attempt(record, status="failed", error_code=record.error_code)
            db.commit()
            sync_job_to_project_json(project_id, job_id, db)
            raise

    # A real provider request in the durable LangGraph flow can have an
    # unknown paid outcome once dispatched.  Do not silently retry or fail
    # over to another provider here: the worker dead-letters the one scene so
    # the seller can explicitly approve a targeted retry or upload instead.
    provider_attempt_limit = (
        1
        if is_production_langgraph and settings.SELLFORM_IMAGE_GENERATION_MODE == "real"
        else 2
    )
    result = None
    for provider_attempt in range(provider_attempt_limit):
        record.attempt_count += 1
        _record_provider_attempt(record, status="running")
        db.commit()
        attempt_started_at = datetime.datetime.utcnow()
        attempt_started_clock = time.monotonic()
        try:
            result = provider.generate(req)
            break
        except Exception as e:
            error_code, error_detail = _split_provider_error(e)
            logger.error("Image generation provider failed: %s", error_code)
            _append_provider_attempt(
                record,
                db,
                provider_adapter_attempt=record.attempt_count,
                provider=str(record.provider or settings.SELLFORM_IMAGE_PROVIDER),
                model=str(record.model or settings.SELLFORM_IMAGE_MODEL),
                dispatch_state="DISPATCHED",
                cost_state="UNKNOWN_AFTER_DISPATCH",
                actual_cost=None,
                currency="credit",
                usage={"availability": "missing"},
                outcome_code=error_code,
                started_at=attempt_started_at,
                completed_at=datetime.datetime.utcnow(),
                latency_ms=int((time.monotonic() - attempt_started_clock) * 1000),
            )
            _record_provider_attempt(record, status="failed", error_code=error_code)
            if (
                error_code not in RETRYABLE_PROVIDER_ERRORS
                or provider_attempt == provider_attempt_limit - 1
            ):
                record.status = "failed"
                record.provider = settings.SELLFORM_IMAGE_PROVIDER
                record.model = settings.SELLFORM_IMAGE_MODEL
                record.error_code = error_code
                record.warnings = [error_detail]
                _record_provider_attempt(record, status="failed", error_code=error_code)
                db.commit()
                sync_job_to_project_json(project_id, job_id, db)
                raise

    if result is None:
        raise RuntimeError("PROVIDER_ERROR")

    result_usage, reported_cost, currency = normalize_provider_usage(result.usage_metadata)
    if reported_cost is None:
        cost_state = "UNKNOWN_AFTER_DISPATCH"
    elif reported_cost == 0:
        cost_state = "EXPLICIT_ZERO"
    else:
        cost_state = "KNOWN"
    result_code = "SUCCESS" if result.status == "success" else "PROVIDER_RESULT_ERROR"
    _append_provider_attempt(
        record,
        db,
        provider_adapter_attempt=record.attempt_count,
        provider=str(result.provider or record.provider or settings.SELLFORM_IMAGE_PROVIDER),
        model=str(result.model or record.model or settings.SELLFORM_IMAGE_MODEL),
        dispatch_state="DISPATCHED",
        cost_state=cost_state,
        actual_cost=reported_cost,
        currency=currency,
        usage=result_usage,
        outcome_code=result_code,
        started_at=attempt_started_at,
        completed_at=datetime.datetime.utcnow(),
        latency_ms=int((time.monotonic() - attempt_started_clock) * 1000),
    )
    if not is_production_langgraph and reported_cost is not None:
        # Legacy callers have no durable run scope. Preserve their established
        # per-job projection without making it an LG-13 aggregation authority.
        record.actual_cost = reported_cost
    record.usage_metadata = {**dict(record.usage_metadata or {}), "provider_usage": result_usage}
    if result.status != "success":
        record.status = "failed"
        record.provider = result.provider
        record.model = result.model
        record.error_code = result_code
        record.warnings = ["Provider returned a non-success result."]
        _record_provider_attempt(record, status="failed", error_code=result_code)
        db.commit()
        sync_job_to_project_json(project_id, job_id, db)
        raise RuntimeError(result_code)

    # Validate before persisting a generated asset.
    try:
        # Validate quality & decodability
        img = ProductIdentityValidator.validate_image_quality(
            content_bytes=result.content,
            mime_type=result.mime_type,
            min_width=512,
            min_height=512
        )
        
        # Validate identity preservation & exclusions
        warnings = []
        identity_report: dict[str, Any] | None = None
        if record.preserve_product_identity:
            if is_production_langgraph:
                scene_prompt = dict((record.input_snapshot or {}).get("scene_prompt") or {})
                identity_report = ProductIdentityValidator.inspect_identity_preservation(
                    img=img,
                    source_asset_paths=source_asset_paths,
                    prompt=record.prompt,
                    role=record.role,
                    identity_constraints=dict(scene_prompt.get("identity_constraints") or {}),
                )
                # Preserve only the provider interface's bounded visual
                # observation.  It remains non-factual QA evidence and is
                # checked against frozen Truth/confirmation when the child
                # DetailPage is evaluated.
                if result.observed_identity:
                    identity_report = {
                        **identity_report,
                        "observed_identity": dict(result.observed_identity),
                    }
                warnings = list(identity_report.get("warnings") or [])
            else:
                warnings = ProductIdentityValidator.validate_identity_preservation(
                    img=img,
                    source_asset_paths=source_asset_paths,
                    prompt=record.prompt,
                    role=record.role
                )
        elif is_production_langgraph:
            identity_report = {"status": "not_run", "checks": {}, "warnings": []}

    except ProductIdentityValidationError as e:
        logger.warning(f"Product identity validation failed for job '{job_id}': {e}")
        record.status = "failed" if "Output rejected:" in str(e) else "blocked"
        # Extract error code name or default to QUALITY_GATE_FAILED / IDENTITY_GATE_REJECTED
        err_msg = str(e)
        if "rejected" in err_msg.lower():
            record.error_code = "IDENTITY_GATE_REJECTED"
        else:
            record.error_code = "QUALITY_GATE_FAILED"
        record.validation_result = (
            _lg9_pre_asset_failure_report(e)
            if is_production_langgraph
            else {"status": "blocked", "reason": err_msg[:500]}
        )
        db.commit()
        sync_job_to_project_json(project_id, job_id, db)
        return record

    extension = {
        "image/jpeg": "jpg",
        "image/webp": "webp",
    }.get(result.mime_type, "png")
    filename = f"ai_generated/ai_{job_id}_{record.attempt_count}.{extension}"
    full_path = os.path.join(settings.UPLOAD_DIR, filename)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    try:
        with open(full_path, "wb") as output_file:
            output_file.write(result.content)
    except Exception:
        record.status = "failed"
        record.error_code = "FILE_SAVE_ERROR"
        db.commit()
        sync_job_to_project_json(project_id, job_id, db)
        raise

    output_asset = Asset(
        project_id=project_id,
        source_type="ai_generated",
        # A generated candidate is not a final-page asset until the seller
        # approves this exact scene in image_review (IMG-10).
        usage_status="blocked",
        filename=filename,
        file_path=full_path,
        mime_type=result.mime_type,
        file_size=len(result.content),
        quality_status="accepted",
        identity_status="passed" if not warnings else "needs_review",
    )
    db.add(output_asset)
    db.flush()

    # Generated images must not carry supplier Chinese copy.  OCR is best
    # effort locally; a detected Chinese string is a hard block, while any
    # other detected text remains visible for seller identity review.
    ocr_text = ""
    ocr_source = "not_run"
    try:
        from src.services.asset_understanding_service import extract_ocr_blocks

        ocr_blocks, ocr_source = extract_ocr_blocks(output_asset)
        ocr_text = " ".join(str(block.get("text") or "") for block in ocr_blocks).strip()
        output_asset.ocr_text = ocr_text or None
    except Exception:
        ocr_source = "ocr_check_failed"

    db.flush()
    output_risks = auto_placement_risk_codes(output_asset, db)
    lg9_validation = (
        _lg9_validation_report(
            record,
            output_asset,
            db,
            identity_warnings=warnings,
            identity_report=identity_report,
            ocr_text=ocr_text,
            ocr_source=ocr_source,
            risk_codes=output_risks,
            revised_prompt=result.revised_prompt,
        )
        if is_production_langgraph
        else None
    )
    if output_risks or (lg9_validation and lg9_validation["status"] == "blocked"):
        output_asset.quality_status = "rejected"
        output_asset.identity_status = "rejected"
        record.output_asset_id = output_asset.id
        record.provider = result.provider
        record.model = result.model
        record.status = "blocked"
        record.error_code = "UNSAFE_GENERATED_CONTENT_DETECTED" if output_risks else "RIGHTS_BLOCKED"
        risk_labels = {
            "foreign_text_exposed": "외국어 문구",
            "phone_number_exposed": "전화번호",
            "price_exposed": "가격",
            "qr_code_review": "QR 코드",
            "market_or_competitor_text": "마켓·경쟁사 문구",
            "supplier_text_exposed": "공급처 문구",
        }
        detected = ", ".join(risk_labels.get(code, code) for code in output_risks)
        record.warnings = (
            [f"생성 결과에서 금지 요소({detected})가 감지되어 최종 사용을 차단했습니다."]
            if output_risks
            else ["장면 프롬프트의 기준 이미지 권리 상태가 차단되어 후보를 승인할 수 없습니다."]
        )
        record.validation_result = lg9_validation or {
            "status": "blocked",
            "checks": {"content_safety": "blocked", "identity": "not_approved", "rights": "passed"},
            "risk_codes": output_risks,
            "ocr_source": ocr_source,
            "ocr_text": ocr_text[:500],
        }
        _record_provider_attempt(record, status="blocked", error_code=record.error_code)
        db.commit()
        sync_job_to_project_json(project_id, job_id, db)
        return record

    record.output_asset_id = output_asset.id
    record.provider = result.provider
    record.model = result.model
    record.status = "needs_review"
    text_warning = "생성 이미지에서 텍스트가 감지되어 원본·상표·문구 복제 여부를 확인해 주세요." if ocr_text else None
    record.warnings = [*warnings, *([text_warning] if text_warning else [])] or None
    record.error_code = None
    _record_provider_attempt(record, status="needs_review")
    record.seed = (result.usage_metadata or {}).get("seed") if isinstance(result.usage_metadata, dict) else None
    record.validation_result = lg9_validation or {
        "status": "needs_review" if (warnings or ocr_text) else "passed",
        "checks": {
            "image_quality": "passed",
            "identity": "needs_review" if warnings else "passed",
            "supplier_text": "needs_review" if ocr_text else "passed",
            "supplier_layout": "passed",
            "rights": "passed",
        },
        "warnings": record.warnings or [],
        "ocr_source": ocr_source,
        "ocr_text": ocr_text[:500],
        "revised_prompt": result.revised_prompt,
    }
    snapshot = dict(record.input_snapshot or {})
    if result.revised_prompt:
        snapshot["provider_revised_prompt"] = result.revised_prompt
    record.input_snapshot = snapshot
    db.commit()
    sync_job_to_project_json(project_id, job_id, db)
    return record


class ImageGenerationService:
    def __init__(self, db: Optional[Session] = None):
        self.db = db

    def review_generated_asset(
        self,
        source_asset_id: str,
        generated_asset_id: str,
        product_identity_required: bool = True
    ) -> dict:
        if not product_identity_required:
            return {
                "identity_check": {
                    "status": "passed",
                    "warnings": []
                }
            }

        # In mock/test mode where DB session is None or assets cannot be resolved
        if not self.db:
            return {
                "identity_check": {
                    "status": "needs_review",
                    "warnings": ["Mock mode: Confidence cannot be measured without DB context."]
                }
            }

        # Fetch assets
        source_asset = self.db.query(Asset).filter(Asset.id == source_asset_id).first()
        generated_asset = self.db.query(Asset).filter(Asset.id == generated_asset_id).first()

        if not source_asset or not generated_asset:
            return {
                "identity_check": {
                    "status": "needs_review",
                    "warnings": ["Assets not found in database."]
                }
            }

        # If files do not exist (e.g. mock assets or dummy paths in testing),
        # return needs_review when confidence cannot be measured.
        # Do not pretend identity is passed without evidence.
        if not source_asset.file_path or not os.path.exists(source_asset.file_path) \
           or not generated_asset.file_path or not os.path.exists(generated_asset.file_path):
            return {
                "identity_check": {
                    "status": "needs_review",
                    "warnings": ["Source or generated asset files are missing. Confidence cannot be measured."]
                }
            }

        try:
            with open(generated_asset.file_path, "rb") as f:
                content = f.read()

            img = ProductIdentityValidator.validate_image_quality(
                content_bytes=content,
                mime_type=generated_asset.mime_type
            )

            # Query job details for role/prompt if available
            job = self.db.query(ImageGenerationJobRecord).filter(
                ImageGenerationJobRecord.output_asset_id == generated_asset_id
            ).first()

            prompt = job.prompt if job else "product image"
            role = job.role if job else "representative_product"

            warnings = ProductIdentityValidator.validate_identity_preservation(
                img=img,
                source_asset_paths=[source_asset.file_path],
                prompt=prompt,
                role=role
            )

            status = "needs_review" if warnings else "passed"
            return {
                "identity_check": {
                    "status": status,
                    "warnings": warnings
                }
            }

        except ProductIdentityValidationError as e:
            return {
                "identity_check": {
                    "status": "failed",
                    "warnings": [str(e)]
                }
            }
        except Exception as e:
            return {
                "identity_check": {
                    "status": "needs_review",
                    "warnings": [f"Visual validation failed: {str(e)}"]
                }
            }
