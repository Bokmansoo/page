import os
import uuid
import logging
from typing import Optional, List, Any
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from src.config import settings
from src.db.models import ProductProject, Asset, ImageGenerationJobRecord
from src.services.image_generation_provider import ImageGenerationRequest, ImageGenerationResult
from src.services.commerce_content_quality_service import auto_placement_risk_codes
from src.services.generation_provider_adapter import get_image_generation_adapter
from src.services.image_asset_inspector import inspect_asset
from src.services.product_identity_validator import ProductIdentityValidator, ProductIdentityValidationError

logger = logging.getLogger(__name__)
RETRYABLE_PROVIDER_ERRORS = {"RATE_LIMIT_EXCEEDED", "TIMEOUT"}
LG9_VALIDATION_SCHEMA_VERSION = "lg9-image-validation-v1"


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
    detail = " ".join(str(error).split())[:500]
    code = detail.split(":", 1)[0].strip() or "PROVIDER_ERROR"
    return code, detail


def _is_production_langgraph_job(record: ImageGenerationJobRecord) -> bool:
    """Keep LG-9 reporting on the production LangGraph execution path only."""

    return bool((record.usage_metadata or {}).get("langgraph_run_id"))


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
        if settings.SELLFORM_IMAGE_GENERATION_MODE == "real":
            provider = get_image_generation_adapter(record.provider or settings.SELLFORM_IMAGE_PROVIDER, record.model)
        else:
            from src.services.image_generation_provider import MockImageGenerationProvider
            provider = MockImageGenerationProvider()

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
        try:
            result = provider.generate(req)
            break
        except Exception as e:
            error_code, error_detail = _split_provider_error(e)
            logger.error(f"Image generation provider failed: {error_detail}")
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
        result_usage = dict(result.usage_metadata or {})
        reported_cost = result_usage.get("actual_cost", result_usage.get("cost"))
        if isinstance(reported_cost, (int, float)) and not isinstance(reported_cost, bool):
            record.actual_cost = float(reported_cost)
        record.usage_metadata = {**dict(record.usage_metadata or {}), **result_usage}
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
    result_usage = dict(result.usage_metadata or {})
    reported_cost = result_usage.get("actual_cost", result_usage.get("cost"))
    if isinstance(reported_cost, (int, float)) and not isinstance(reported_cost, bool):
        record.actual_cost = float(reported_cost)
    record.usage_metadata = {
        **dict(record.usage_metadata or {}),
        **result_usage,
    }
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
