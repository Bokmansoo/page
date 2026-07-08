import os
import uuid
import logging
from typing import Optional, List, Any
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from src.config import settings
from src.db.models import ProductProject, Asset, ImageGenerationJobRecord
from src.services.image_generation_provider import ImageGenerationRequest, ImageGenerationResult
from src.services.openai_image_provider import OpenAIImageProvider
from src.services.product_identity_validator import ProductIdentityValidator, ProductIdentityValidationError

logger = logging.getLogger(__name__)
RETRYABLE_PROVIDER_ERRORS = {"RATE_LIMIT_EXCEEDED", "TIMEOUT"}


def _split_provider_error(error: Exception) -> tuple[str, str]:
    detail = " ".join(str(error).split())[:500]
    code = detail.split(":", 1)[0].strip() or "PROVIDER_ERROR"
    return code, detail


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
            provider = OpenAIImageProvider(model=record.model)
        else:
            from src.services.image_generation_provider import MockImageGenerationProvider
            provider = MockImageGenerationProvider()

    result = None
    for provider_attempt in range(2):
        record.attempt_count += 1
        db.commit()
        try:
            result = provider.generate(req)
            break
        except Exception as e:
            error_code, error_detail = _split_provider_error(e)
            logger.error(f"Image generation provider failed: {error_detail}")
            if error_code not in RETRYABLE_PROVIDER_ERRORS or provider_attempt == 1:
                record.status = "failed"
                record.provider = settings.SELLFORM_IMAGE_PROVIDER
                record.model = settings.SELLFORM_IMAGE_MODEL
                record.error_code = error_code
                record.warnings = [error_detail]
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
        if record.preserve_product_identity:
            warnings = ProductIdentityValidator.validate_identity_preservation(
                img=img,
                source_asset_paths=source_asset_paths,
                prompt=record.prompt,
                role=record.role
            )

    except ProductIdentityValidationError as e:
        logger.warning(f"Product identity validation failed for job '{job_id}': {e}")
        record.status = "failed"
        # Extract error code name or default to QUALITY_GATE_FAILED / IDENTITY_GATE_REJECTED
        err_msg = str(e)
        if "rejected" in err_msg.lower():
            record.error_code = "IDENTITY_GATE_REJECTED"
        else:
            record.error_code = "QUALITY_GATE_FAILED"
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
        filename=filename,
        file_path=full_path,
        mime_type=result.mime_type,
        file_size=len(result.content),
    )
    db.add(output_asset)
    db.flush()

    record.output_asset_id = output_asset.id
    record.provider = result.provider
    record.model = result.model
    record.status = "needs_review"
    record.warnings = warnings or None
    record.error_code = None
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
