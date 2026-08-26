"""LG-5R durable image-generation domain service.

Only compact IDs, hashes and summaries enter LangGraph state. Provider work is
persisted in a DB outbox and processed by ``image_generation_worker``.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from copy import deepcopy
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models import (
    AgentRun,
    Asset,
    DetailPageVersion,
    ImageGenerationCostApprovalRecord,
    ImageGenerationJobRecord,
    ImageGenerationOutboxRecord,
    ProductFact,
    ProductProject,
)
from src.services.commerce_policy import is_asset_final_output_eligible
from src.services.product_identity_validator import (
    ProductIdentityValidationError,
    build_frozen_image_quality_evidence,
)
from src.services.storyboard_image_generation_service import (
    StoryboardImageGenerationError,
    approve_storyboard_job,
    attach_manual_storyboard_output,
    build_storyboard_generation_contracts,
    reject_storyboard_job,
    start_storyboard_job,
    storyboard_image_generation_is_available,
)
from src.services.storyboard_service import approve_storyboard


LG9_APPROVED_ASSET_MANIFEST_SCHEMA_VERSION = "lg9-approved-asset-manifest-v1"


class ImageGenerationGateError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


PENDING_STATUSES = {"queued", "leased", "running", "generating"}
REVIEWABLE_STATUSES = {"needs_review"}
FAILED_STATUSES = {"failed", "blocked", "rejected", "cancelled", "dead_letter"}


def approve_graph_storyboard(*, project_id: str, db: Session) -> dict[str, Any]:
    """Bridge LG-4 planning approval to the canonical storyboard invariant.

    LG-5R still depends on the seller-approved storyboard contract established
    in LG-4.  Keeping this bridge here preserves that boundary while the new
    cost/outbox pipeline remains responsible only for paid generation work.
    """

    project = _project(project_id, db)
    # Graph visual planning stores source references in ``image_asset_id`` for
    # editor previews. They are generation inputs, not automatically approved
    # final-output assignments. Normalize them into candidate references before
    # applying the canonical storyboard approval invariant.
    draft = deepcopy(project.planning_draft or {})
    seen_final_assets: set[str] = set()
    for card in draft.get("cards") or []:
        asset_id = str(card.get("image_asset_id") or "")
        if not asset_id:
            continue
        if card.get("image_requirement") == "ai_redesign_required" or asset_id in seen_final_assets:
            card["image_asset_id"] = None
        else:
            seen_final_assets.add(asset_id)
    project.planning_draft = draft
    assets = db.query(Asset).filter(Asset.project_id == project_id).all()
    facts = db.query(ProductFact).filter(ProductFact.project_id == project_id).all()
    approved = approve_storyboard(project, assets, facts, db, user_id=None)
    db.add(project)
    db.commit()
    return approved


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _project(project_id: str, db: Session) -> ProductProject:
    project = db.query(ProductProject).filter(ProductProject.id == project_id).first()
    if project is None:
        raise ImageGenerationGateError("PROJECT_NOT_FOUND", "이미지 생성을 위한 프로젝트를 찾을 수 없습니다.")
    return project


def _run(run_id: str, project_id: str, db: Session) -> AgentRun:
    run = db.query(AgentRun).filter(AgentRun.id == run_id, AgentRun.project_id == project_id).first()
    if run is None:
        raise ImageGenerationGateError("GRAPH_RUN_NOT_FOUND", "이미지 생성 실행을 찾을 수 없습니다.")
    return run


def _owned_jobs(project_id: str, run_id: str, db: Session) -> list[ImageGenerationJobRecord]:
    rows = (
        db.query(ImageGenerationJobRecord)
        .filter(ImageGenerationJobRecord.project_id == project_id)
        .order_by(ImageGenerationJobRecord.created_at.asc(), ImageGenerationJobRecord.job_id.asc())
        .all()
    )
    return [row for row in rows if str((row.usage_metadata or {}).get("langgraph_run_id") or "") == run_id]


def _latest_jobs(rows: list[ImageGenerationJobRecord]) -> list[ImageGenerationJobRecord]:
    latest: dict[str, ImageGenerationJobRecord] = {}
    for row in rows:
        scene_id = str(row.scene_id or row.section_id)
        current = latest.get(scene_id)
        if current is None or int(row.generation_attempt or 1) > int(current.generation_attempt or 1):
            latest[scene_id] = row
    return sorted(latest.values(), key=lambda item: (item.created_at or datetime.datetime.min, item.job_id))


def _job_view(job: ImageGenerationJobRecord) -> dict[str, Any]:
    outbox = job.outbox_record
    return {
        "job_id": job.job_id,
        "scene_id": job.scene_id or job.section_id,
        "section_id": job.section_id,
        "role": job.role,
        "status": job.status,
        "output_asset_id": job.output_asset_id,
        "error_code": job.error_code,
        "error_message": (job.warnings or [None])[0],
        "warnings": list(job.warnings or []),
        "validation": dict(job.validation_result or {}),
        "source_asset_ids": list(job.source_asset_ids or []),
        "estimated_cost": job.estimated_cost,
        "actual_cost": job.actual_cost,
        "attempt_count": job.attempt_count,
        "generation_attempt": job.generation_attempt,
        "prompt_version": job.prompt_version,
        "prompt_hash": job.prompt_hash,
        "reference_hash": job.reference_hash,
        "planning_hash": job.planning_hash,
        "input_hash": job.input_hash,
        "idempotency_key": job.idempotency_key,
        "required_for_completion": bool(job.required_for_completion),
        "outbox_status": outbox.status if outbox else None,
    }


def _summary(rows: list[ImageGenerationJobRecord]) -> dict[str, Any]:
    latest = _latest_jobs(rows)
    required = [job for job in latest if job.required_for_completion]
    remaining = [str(job.scene_id or job.section_id) for job in required if job.status != "approved"]
    return {
        "job_ids": [job.job_id for job in latest],
        "jobs": [_job_view(job) for job in latest],
        "attempt_job_ids": [job.job_id for job in rows],
        "estimated_cost": sum(float(job.estimated_cost or 0) for job in latest),
        "actual_cost": sum(float(job.actual_cost or 0) for job in rows),
        "pending_count": sum(job.status in PENDING_STATUSES for job in latest),
        "review_count": sum(job.status in REVIEWABLE_STATUSES for job in latest),
        "approved_count": sum(job.status == "approved" for job in required),
        "required_scene_count": len(required),
        "remaining_required_scene_ids": remaining,
        "image_generation_required": bool(required),
        "completion_basis": "approved_required_scenes" if required else "no_required_image_scenes",
        "all_required_scenes_approved": not remaining,
        "approved_asset_ids": [job.output_asset_id for job in required if job.status == "approved" and job.output_asset_id],
        "review_asset_ids": [job.output_asset_id for job in latest if job.status == "needs_review" and job.output_asset_id],
        "failed_job_ids": [job.job_id for job in latest if job.status in FAILED_STATUSES],
    }


def build_approved_asset_manifest(*, run_id: str, project_id: str, db: Session) -> dict[str, Any]:
    """Freeze only seller-approved final assets for the future Page Assembly input."""

    latest = _latest_jobs(_owned_jobs(project_id, run_id, db))
    required = [job for job in latest if job.required_for_completion]
    if not required or any(job.status != "approved" or not job.output_asset_id for job in required):
        raise ImageGenerationGateError(
            "APPROVED_ASSET_MANIFEST_INCOMPLETE",
            "모든 필수 장면을 승인한 뒤에만 Page Assembly asset manifest를 만들 수 있습니다.",
        )

    entries: list[dict[str, Any]] = []
    for job in sorted(
        required,
        key=lambda item: (str(item.scene_id or item.section_id), str(item.section_id or ""), str(item.job_id)),
    ):
        asset = db.query(Asset).filter(
            Asset.id == job.output_asset_id,
            Asset.project_id == project_id,
        ).first()
        if (
            asset is None
            or not is_asset_final_output_eligible(asset)
            or re.fullmatch(r"[0-9a-f]{64}", str(asset.content_hash or "")) is None
        ):
            raise ImageGenerationGateError(
                "APPROVED_ASSET_MANIFEST_INELIGIBLE",
                "승인 장면에 최종 출력으로 사용할 수 없는 asset이 포함되어 있습니다.",
            )
        try:
            frozen_quality_evidence = build_frozen_image_quality_evidence(asset=asset, job=job)
        except ProductIdentityValidationError as exc:
            raise ImageGenerationGateError(
                "APPROVED_ASSET_MANIFEST_INTEGRITY",
                "Approved output cannot be frozen because its bounded image evidence is invalid.",
            ) from exc
        entries.append({
            "scene_id": str(job.scene_id or job.section_id),
            "section_id": job.section_id,
            "job_id": job.job_id,
            "generation_attempt": int(job.generation_attempt or 1),
            "asset_id": asset.id,
            "asset_content_hash": asset.content_hash,
            "provider": job.provider,
            "model": job.model,
            # TASK-12.4 evaluates this immutable evidence, never mutable Asset
            # classification fields or a later generation attempt.
            "lg12_frozen_image_evidence": frozen_quality_evidence,
        })

    manifest = {
        "schema_version": LG9_APPROVED_ASSET_MANIFEST_SCHEMA_VERSION,
        "run_id": run_id,
        "project_id": project_id,
        "assets": entries,
    }
    return {**manifest, "manifest_hash": _hash(manifest)}


def _cost_plan_payload(record: ImageGenerationCostApprovalRecord) -> dict[str, Any]:
    return {
        "approval_id": record.id,
        "cost_plan_hash": record.cost_plan_hash,
        "planning_hash": record.planning_hash,
        "provider": record.provider,
        "model": record.model,
        "scene_count": record.scene_count,
        "scenes": list(record.scene_costs or []),
        "total_estimated_cost": float(record.total_estimated_cost or 0),
        "currency": record.currency,
        "status": record.status,
    }


def _pinned_brand_kit(run: AgentRun) -> tuple[str | None, str | None]:
    """Return the immutable Creative Brief Brand Kit reference for this run."""

    snapshot = dict((run.input_snapshot or {}).get("creative_brief_snapshot") or {})
    return snapshot.get("brand_kit_version_id"), snapshot.get("brand_kit_hash")


def ensure_generation_cost_plan(
    *,
    run_id: str,
    project_id: str,
    db: Session,
    scene_ids: list[str] | None = None,
    allow_no_required_scenes: bool = False,
) -> dict[str, Any]:
    """Persist the exact pre-dispatch cost snapshot without creating jobs."""

    project = _project(project_id, db)
    run = _run(run_id, project_id, db)
    try:
        brand_version_id, brand_hash = _pinned_brand_kit(run)
        contracts = build_storyboard_generation_contracts(
            project,
            db,
            brand_kit_version_id=brand_version_id,
            brand_kit_hash=brand_hash,
        )
    except StoryboardImageGenerationError as error:
        raise ImageGenerationGateError("IMAGE_JOB_PREPARE_FAILED", str(error)) from error
    wanted = set(scene_ids or [])
    if wanted:
        contracts = [item for item in contracts if item["scene_id"] in wanted]
    if not contracts:
        if not allow_no_required_scenes:
            raise ImageGenerationGateError("NO_GENERATION_SCENES", "이미지 생성이 필요한 승인 장면이 없습니다.")
        # A storyboard made entirely from information sections and explicitly
        # seller-supplied photos is a valid zero-cost LG-10 input. Keep this
        # distinct from failed or unapproved required jobs without creating a
        # fake cost approval record or provider work item.
        planning_hash = _hash(project.planning_draft or {})
        plan_hash = _hash({"run_id": run_id, "planning_hash": planning_hash, "scenes": []})
        run.estimated_cost = 0
        run.cost_approval_status = "not_required"
        db.add(run)
        db.commit()
        return {
            "cost_plan_hash": plan_hash,
            "planning_hash": planning_hash,
            "provider": "none",
            "model": "none",
            "scene_count": 0,
            "scenes": [],
            "total_estimated_cost": 0.0,
            "currency": "credit",
            "status": "not_required",
        }
    scenes = [
        {
            "scene_id": item["scene_id"],
            "title": item["scene_title"],
            "role": item["role"],
            "model": item["model"],
            "output_size": item["output_size"],
            "estimated_cost": float(item["estimated_cost"]),
            "prompt_version": item["prompt_version"],
            "prompt_hash": item["prompt_hash"],
            "reference_hash": item["reference_hash"],
            "input_hash": item["input_hash"],
        }
        for item in contracts
    ]
    planning_hash = contracts[0]["planning_hash"]
    plan_hash = _hash({"run_id": run_id, "planning_hash": planning_hash, "scenes": scenes})
    record = db.query(ImageGenerationCostApprovalRecord).filter(
        ImageGenerationCostApprovalRecord.run_id == run_id,
        ImageGenerationCostApprovalRecord.cost_plan_hash == plan_hash,
    ).first()
    if record is None:
        db.query(ImageGenerationCostApprovalRecord).filter(
            ImageGenerationCostApprovalRecord.run_id == run_id,
            ImageGenerationCostApprovalRecord.status.in_(["pending", "deferred"]),
        ).update({ImageGenerationCostApprovalRecord.status: "stale"}, synchronize_session=False)
        record = ImageGenerationCostApprovalRecord(
            workspace_id=run.workspace_id,
            project_id=project_id,
            run_id=run_id,
            thread_id=run.graph_thread_id or run.id,
            planning_hash=planning_hash,
            cost_plan_hash=plan_hash,
            provider=contracts[0]["provider"],
            model=contracts[0]["model"],
            scene_count=len(scenes),
            scene_costs=scenes,
            total_estimated_cost=sum(item["estimated_cost"] for item in scenes),
            currency="credit",
            status="pending",
        )
        db.add(record)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            record = db.query(ImageGenerationCostApprovalRecord).filter(
                ImageGenerationCostApprovalRecord.run_id == run_id,
                ImageGenerationCostApprovalRecord.cost_plan_hash == plan_hash,
            ).one()
    run.estimated_cost = float(record.total_estimated_cost or 0)
    run.cost_approval_status = record.status
    db.add(run)
    db.commit()
    return _cost_plan_payload(record)


def record_cost_decision(
    *, run_id: str, project_id: str, cost_plan_hash: str, decision: str, db: Session
) -> dict[str, Any]:
    run = _run(run_id, project_id, db)
    record = db.query(ImageGenerationCostApprovalRecord).filter(
        ImageGenerationCostApprovalRecord.run_id == run_id,
        ImageGenerationCostApprovalRecord.cost_plan_hash == cost_plan_hash,
    ).with_for_update().first()
    if record is None or record.status == "stale":
        raise ImageGenerationGateError("COST_PLAN_STALE", "비용 계획이 변경되었습니다. 최신 비용을 다시 확인해 주세요.")
    now = datetime.datetime.utcnow()
    if decision == "approve":
        record.status = "approved"
        record.approved_at = record.approved_at or now
        record.approved_by = record.approved_by or run.created_by
        run.cost_approval_status = "approved"
    elif decision == "defer":
        if record.status != "approved":
            record.status = "deferred"
            record.deferred_at = now
        run.cost_approval_status = "deferred"
    else:
        raise ImageGenerationGateError("COST_DECISION_INVALID", "지원하지 않는 비용 승인 결정입니다.")
    db.add_all([record, run])
    db.commit()
    return _cost_plan_payload(record)


def _idempotency_key(project_id: str, contract: dict[str, Any], generation_attempt: int) -> str:
    return _hash(
        {
            "project_id": project_id,
            "scene_id": contract["scene_id"],
            "prompt_version": contract["prompt_version"],
            "reference_hash": contract["reference_hash"],
            "attempt": generation_attempt,
        }
    )


def _immutable_scene_prompt_snapshot(contract: dict[str, Any]) -> dict[str, Any]:
    """Copy and verify the LG-8 prompt payload before it becomes a job input.

    The foreign key makes the source prompt traceable, while this JSON copy
    preserves the exact provider input even if a later scene prompt revision
    becomes active.  A malformed contract must not create a partially pinned
    job that could be dispatched with mismatched prompt metadata.
    """

    snapshot = deepcopy(contract.get("input_snapshot") or {})
    scene_prompt = dict(snapshot.get("scene_prompt") or {})
    expected = {
        "id": contract["scene_prompt_version_id"],
        "scene_id": contract["scene_id"],
        "prompt_version": contract["prompt_version"],
        "prompt_hash": contract["prompt_hash"],
        "reference_hash": contract["reference_hash"],
    }
    is_mismatched = any(scene_prompt.get(key) != value for key, value in expected.items())
    if is_mismatched or not scene_prompt.get("input_hash"):
        raise ImageGenerationGateError(
            "SCENE_PROMPT_SNAPSHOT_INVALID",
            "The image job must be created from one immutable scene prompt snapshot.",
        )
    return snapshot


def prepare_graph_image_jobs(
    *, run_id: str, project_id: str, mode: str, db: Session,
    cost_plan_hash: str | None = None, scene_attempts: dict[str, int] | None = None,
) -> dict[str, Any]:
    project = _project(project_id, db)
    run = _run(run_id, project_id, db)
    approval = db.query(ImageGenerationCostApprovalRecord).filter(
        ImageGenerationCostApprovalRecord.run_id == run_id,
        ImageGenerationCostApprovalRecord.cost_plan_hash == cost_plan_hash,
        ImageGenerationCostApprovalRecord.status == "approved",
    ).first()
    if approval is None:
        raise ImageGenerationGateError("COST_APPROVAL_REQUIRED", "현재 비용 계획을 승인한 뒤 이미지 작업을 만들 수 있습니다.")
    try:
        brand_version_id, brand_hash = _pinned_brand_kit(run)
        contracts = build_storyboard_generation_contracts(
            project,
            db,
            brand_kit_version_id=brand_version_id,
            brand_kit_hash=brand_hash,
        )
    except StoryboardImageGenerationError as error:
        raise ImageGenerationGateError("IMAGE_JOB_PREPARE_FAILED", str(error)) from error
    approved_scenes = {item["scene_id"]: item for item in (approval.scene_costs or [])}
    contracts = [item for item in contracts if item["scene_id"] in approved_scenes]
    if not contracts or any(item["planning_hash"] != approval.planning_hash for item in contracts):
        approval.status = "stale"
        db.commit()
        raise ImageGenerationGateError("COST_PLAN_STALE", "스토리보드 또는 기준 사진이 변경되었습니다. 비용을 다시 확인해 주세요.")
    attempts = scene_attempts or {}
    for contract in contracts:
        approved_scene = approved_scenes[contract["scene_id"]]
        if approved_scene.get("input_hash") != contract["input_hash"]:
            approval.status = "stale"
            db.commit()
            raise ImageGenerationGateError("COST_PLAN_STALE", "프롬프트 또는 기준 사진이 변경되었습니다. 비용을 다시 확인해 주세요.")
        generation_attempt = int(attempts.get(contract["scene_id"], 1))
        key = _idempotency_key(project_id, contract, generation_attempt)
        existing = db.query(ImageGenerationJobRecord).filter(ImageGenerationJobRecord.idempotency_key == key).first()
        if existing is not None:
            if existing.input_hash != contract["input_hash"]:
                raise ImageGenerationGateError("IDEMPOTENCY_INPUT_MISMATCH", "같은 작업 키의 입력이 일치하지 않습니다.")
            continue
        previous = (
            db.query(ImageGenerationJobRecord)
            .filter(
                ImageGenerationJobRecord.project_id == project_id,
                ImageGenerationJobRecord.scene_id == contract["scene_id"],
                ImageGenerationJobRecord.generation_attempt < generation_attempt,
            )
            .order_by(ImageGenerationJobRecord.generation_attempt.desc())
            .first()
        )
        job = ImageGenerationJobRecord(
            project_id=project_id,
            job_id=f"lg5r-{key[:24]}",
            section_id=contract["section_id"],
            scene_id=contract["scene_id"],
            role=contract["role"],
            source_asset_ids=contract["source_asset_ids"],
            prompt=contract["prompt"],
            negative_prompt=contract["negative_prompt"],
            preserve_product_identity=True,
            output_size=contract["output_size"],
            cost_tier=contract["cost_tier"],
            status="blocked" if contract["blocker_code"] else "awaiting_approval",
            provider=contract["provider"],
            model=contract["model"],
            error_code=contract["blocker_code"],
            warnings=contract["blocker_warnings"] or ["비용 승인 완료. durable worker 전송 대기 중입니다."],
            input_snapshot=_immutable_scene_prompt_snapshot(contract),
            validation_result={"status": "blocked" if contract["blocker_code"] else "pending"},
            estimated_cost=contract["estimated_cost"],
            usage_metadata={
                "langgraph_run_id": run_id,
                "langgraph_thread_id": run.graph_thread_id or run.id,
                "langgraph_mode": mode,
                "cost_approval_id": approval.id,
                "cost_plan_hash": approval.cost_plan_hash,
            },
            prompt_version=contract["prompt_version"],
            prompt_hash=contract["prompt_hash"],
            reference_hash=contract["reference_hash"],
            planning_hash=contract["planning_hash"],
            input_hash=contract["input_hash"],
            generation_attempt=generation_attempt,
            idempotency_key=key,
            required_for_completion=contract["required_for_completion"],
            supersedes_job_id=previous.job_id if previous else None,
            scene_prompt_version_id=contract["scene_prompt_version_id"],
        )
        db.add(job)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            existing = db.query(ImageGenerationJobRecord).filter(ImageGenerationJobRecord.idempotency_key == key).one()
            if existing.input_hash != contract["input_hash"]:
                raise ImageGenerationGateError("IDEMPOTENCY_INPUT_MISMATCH", "같은 작업 키의 입력이 일치하지 않습니다.")
    return _summary(_owned_jobs(project_id, run_id, db))


def _provider_gate(mode: str) -> None:
    if mode == "mock":
        return
    if not storyboard_image_generation_is_available():
        raise ImageGenerationGateError(
            "API_KEY_MISSING",
            "이미지 제공자 API 키가 준비되지 않았습니다. 키와 생성 모드를 확인한 뒤 같은 실행을 재개해 주세요.",
        )


def dispatch_graph_image_jobs(*, run_id: str, project_id: str, mode: str, db: Session) -> dict[str, Any]:
    """Persist queue deliveries only; provider execution never occurs here."""

    _provider_gate(mode)
    project = _project(project_id, db)
    run = _run(run_id, project_id, db)
    rows = _owned_jobs(project_id, run_id, db)
    if not rows:
        raise ImageGenerationGateError("IMAGE_JOB_MISSING", "준비된 이미지 생성 작업을 찾을 수 없습니다.")
    for job in _latest_jobs(rows):
        if job.status in {"approved", "needs_review", "queued", "running", "generating"}:
            continue
        if job.status == "blocked":
            continue
        try:
            started = start_storyboard_job(project, job.job_id, True, db, allow_mock_provider=(mode == "mock"))
        except StoryboardImageGenerationError as error:
            raise ImageGenerationGateError("IMAGE_JOB_DISPATCH_FAILED", str(error)) from error
        if not started.get("dispatch_required"):
            continue
        outbox = db.query(ImageGenerationOutboxRecord).filter(
            ImageGenerationOutboxRecord.idempotency_key == job.idempotency_key
        ).first()
        if outbox is None:
            outbox = ImageGenerationOutboxRecord(
                workspace_id=run.workspace_id,
                project_id=project_id,
                run_id=run_id,
                thread_id=run.graph_thread_id or run.id,
                image_job_id=job.id,
                job_id=job.job_id,
                idempotency_key=str(job.idempotency_key),
                provider_mode=mode,
                status="queued",
            )
            db.add(outbox)
            try:
                db.flush()
                from src.services.langgraph_run_service import AgentRunEventJournal

                AgentRunEventJournal.append_timing_event(
                    run,
                    db,
                    event_type="delivery_enqueued",
                    timing={
                        "outbox": {"id": outbox.id, "version": 1, "hash": str(outbox.idempotency_key)},
                        "attempt": 0,
                    },
                )
                db.commit()
            except IntegrityError:
                db.rollback()
    return _summary(_owned_jobs(project_id, run_id, db))


def collect_graph_image_results(*, run_id: str, project_id: str, db: Session) -> dict[str, Any]:
    rows = _owned_jobs(project_id, run_id, db)
    if not rows:
        raise ImageGenerationGateError("IMAGE_JOB_MISSING", "이미지 생성 작업을 찾을 수 없습니다.")
    return _summary(rows)


def _next_attempts(rows: list[ImageGenerationJobRecord], scene_ids: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for scene_id in scene_ids:
        attempts = [int(row.generation_attempt or 1) for row in rows if str(row.scene_id or row.section_id) == scene_id]
        result[scene_id] = max(attempts or [0]) + 1
    return result


def _lg11_source_scene_job(*, source_version: DetailPageVersion, scene_id: str, db: Session) -> ImageGenerationJobRecord:
    """Resolve a scene's immutable LG-9 job from the frozen version manifest."""

    snapshot = dict(source_version.sections_json or {})
    canonical = dict(dict(snapshot.get("lg10") or {}).get("canonical_page_assembly_input") or {})
    manifest = dict(canonical.get("approved_asset_manifest") or {})
    entry = next((dict(item) for item in manifest.get("assets") or [] if str(item.get("scene_id") or "") == scene_id), None)
    if entry is None:
        raise ImageGenerationGateError("FROZEN_SCENE_NOT_FOUND", "The selected approved scene is not in the frozen version.")
    job = db.query(ImageGenerationJobRecord).filter(
        ImageGenerationJobRecord.project_id == source_version.project_id,
        ImageGenerationJobRecord.job_id == str(entry.get("job_id") or ""),
    ).first()
    if job is None or job.status != "approved" or str(job.output_asset_id or "") != str(entry.get("asset_id") or ""):
        raise ImageGenerationGateError("FROZEN_SCENE_SOURCE_INVALID", "The frozen scene no longer has its immutable approved generation input.")
    asset = db.query(Asset).filter(Asset.id == job.output_asset_id, Asset.project_id == source_version.project_id).first()
    if asset is None or str(asset.content_hash or "") != str(entry.get("asset_content_hash") or ""):
        raise ImageGenerationGateError("FROZEN_SCENE_ASSET_MISMATCH", "The frozen scene asset identity does not match its bytes.")
    return job


def ensure_lg11_scene_regeneration_cost_plan(*, run: AgentRun, source_version: DetailPageVersion, scene_id: str, db: Session) -> dict[str, Any]:
    """Create one immutable, source-version-scoped cost plan for an LG-11 scene."""

    source = _lg11_source_scene_job(source_version=source_version, scene_id=scene_id, db=db)
    scene = {
        "scene_id": scene_id, "section_id": source.section_id, "source_job_id": source.job_id,
        "prompt_hash": source.prompt_hash, "reference_hash": source.reference_hash, "input_hash": source.input_hash,
        "estimated_cost": float(source.estimated_cost or 0), "model": source.model, "output_size": source.output_size,
    }
    planning_hash = _hash({"source_version_id": source_version.id, "snapshot_hash": dict(source_version.sections_json or {}).get("snapshot_hash"), "scene": scene})
    plan_hash = _hash({"run_id": run.id, "planning_hash": planning_hash, "scenes": [scene]})
    record = db.query(ImageGenerationCostApprovalRecord).filter_by(run_id=run.id, cost_plan_hash=plan_hash).first()
    if record is None:
        record = ImageGenerationCostApprovalRecord(
            workspace_id=run.workspace_id, project_id=run.project_id, run_id=run.id, thread_id=run.graph_thread_id or run.id,
            planning_hash=planning_hash, cost_plan_hash=plan_hash, provider=str(source.provider or ""), model=str(source.model or ""),
            scene_count=1, scene_costs=[scene], total_estimated_cost=float(source.estimated_cost or 0), currency="credit", status="pending",
        )
        db.add(record); db.commit()
    # Keep the AgentRun operational projection aligned with the same durable
    # LG-9 approval record used by ordinary image generation.
    run.estimated_cost = float(record.total_estimated_cost or 0)
    run.cost_approval_status = record.status
    db.add(run)
    db.commit()
    return _cost_plan_payload(record)


def prepare_lg11_scene_regeneration(*, run: AgentRun, source_version: DetailPageVersion, scene_id: str, cost_plan_hash: str, db: Session) -> dict[str, Any]:
    approval = db.query(ImageGenerationCostApprovalRecord).filter_by(run_id=run.id, cost_plan_hash=cost_plan_hash, status="approved").first()
    if approval is None:
        raise ImageGenerationGateError("COST_APPROVAL_REQUIRED", "Approve the frozen scene cost before provider dispatch.")
    source = _lg11_source_scene_job(source_version=source_version, scene_id=scene_id, db=db)
    key = _hash({"lg11_run_id": run.id, "source_version_id": source_version.id, "source_job_id": source.job_id, "cost_plan_hash": cost_plan_hash})
    existing = db.query(ImageGenerationJobRecord).filter_by(idempotency_key=key).first()
    if existing is None:
        existing = ImageGenerationJobRecord(
            project_id=run.project_id, job_id=f"lg11-{key[:24]}", section_id=source.section_id, scene_id=scene_id, role=source.role,
            source_asset_ids=deepcopy(source.source_asset_ids or []), prompt=source.prompt, negative_prompt=source.negative_prompt,
            preserve_product_identity=True, output_size=source.output_size, cost_tier=source.cost_tier, status="awaiting_approval",
            provider=source.provider, model=source.model, warnings=["LG-11 scene regeneration approved; durable dispatch pending."],
            input_snapshot=deepcopy(source.input_snapshot or {}), validation_result={"status": "pending"}, estimated_cost=source.estimated_cost,
            usage_metadata={"langgraph_run_id": run.id, "langgraph_thread_id": run.graph_thread_id or run.id, "langgraph_mode": run.mode,
                            "cost_approval_id": approval.id, "cost_plan_hash": cost_plan_hash, "lg11_source_version_id": source_version.id, "lg11_source_job_id": source.job_id},
            prompt_version=source.prompt_version, prompt_hash=source.prompt_hash, reference_hash=source.reference_hash, planning_hash=approval.planning_hash,
            input_hash=source.input_hash, generation_attempt=int(source.generation_attempt or 1) + 1, idempotency_key=key,
            required_for_completion=True, supersedes_job_id=source.job_id, scene_prompt_version_id=source.scene_prompt_version_id,
        )
        db.add(existing); db.commit()
    return _summary(_owned_jobs(run.project_id, run.id, db))


def prepare_lg11_seller_asset_replacement(*, run: AgentRun, source_version: DetailPageVersion, scene_id: str, asset_id: str, seller_attested: bool, db: Session) -> dict[str, Any]:
    source = _lg11_source_scene_job(source_version=source_version, scene_id=scene_id, db=db)
    key = _hash({"lg11_run_id": run.id, "source_version_id": source_version.id, "source_job_id": source.job_id, "asset_id": asset_id})
    job = db.query(ImageGenerationJobRecord).filter_by(idempotency_key=key).first()
    if job is None:
        job = ImageGenerationJobRecord(project_id=run.project_id, job_id=f"lg11-{key[:24]}", section_id=source.section_id, scene_id=scene_id, role=source.role,
            source_asset_ids=deepcopy(source.source_asset_ids or []), prompt=source.prompt, negative_prompt=source.negative_prompt, preserve_product_identity=True,
            output_size=source.output_size, cost_tier=source.cost_tier, status="awaiting_approval", provider="manual_upload", model="seller_final_asset",
            input_snapshot=deepcopy(source.input_snapshot or {}), validation_result={"status": "pending"}, estimated_cost=0.0,
            usage_metadata={"langgraph_run_id": run.id, "langgraph_thread_id": run.graph_thread_id or run.id,
                            "langgraph_mode": run.mode, "lg11_source_version_id": source_version.id,
                            "lg11_source_job_id": source.job_id},
            prompt_version=source.prompt_version, prompt_hash=source.prompt_hash, reference_hash=source.reference_hash, planning_hash=source.planning_hash,
            input_hash=source.input_hash, generation_attempt=int(source.generation_attempt or 1) + 1, idempotency_key=key, required_for_completion=True,
            supersedes_job_id=source.job_id, scene_prompt_version_id=source.scene_prompt_version_id)
        db.add(job); db.commit()
    try:
        attach_manual_storyboard_output(_project(run.project_id, db), job.job_id, asset_id, seller_attested, db)
    except StoryboardImageGenerationError as error:
        # A replacement-rights rejection is a terminal result for this target
        # edit, not an orchestration failure.  Keep every source/sibling asset
        # intact and require a fresh explicit edit run for another candidate.
        job.status = "blocked"
        job.error_code = "SELLER_REPLACEMENT_INELIGIBLE"
        job.warnings = [str(error)]
        job.validation_result = {"status": "blocked", "reason": "seller_replacement_ineligible"}
        db.commit()
    return _summary(_owned_jobs(run.project_id, run.id, db))


def apply_image_review(
    *, run_id: str, project_id: str, decision: str, job_id: str = "", asset_id: str = "",
    seller_attested: bool = False, db: Session,
) -> dict[str, Any]:
    """Apply one scene decision and retain every sibling and prior attempt."""

    project = _project(project_id, db)
    rows = _owned_jobs(project_id, run_id, db)
    latest = _latest_jobs(rows)
    if not latest:
        raise ImageGenerationGateError("IMAGE_JOB_MISSING", "검수할 이미지 생성 작업을 찾을 수 없습니다.")
    by_id = {job.job_id: job for job in latest}
    target = by_id.get(job_id) if job_id else None
    if decision in {"approve", "reject", "upload"} and target is None:
        raise ImageGenerationGateError("IMAGE_REVIEW_JOB_REQUIRED", "처리할 장면을 한 개 선택해 주세요.")
    try:
        if decision == "approve" and target is not None:
            # A downstream failure can leave an image-review checkpoint behind
            # after this job was already durably approved. Replaying that exact
            # checkpoint must rebuild the manifest/finalization input, not try
            # to approve the same immutable job a second time.
            if target.status != "approved":
                approve_storyboard_job(project, target.job_id, db, identity_confirmed=True)
                target.approved_at = datetime.datetime.utcnow()
                db.commit()
        elif decision == "reject" and target is not None:
            reject_storyboard_job(project, target.job_id, db)
            target.rejected_at = datetime.datetime.utcnow()
            db.commit()
        elif decision == "upload" and target is not None:
            if not asset_id:
                raise ImageGenerationGateError("UPLOAD_ASSET_REQUIRED", "직접 업로드할 사진을 선택해 주세요.")
            attach_manual_storyboard_output(project, target.job_id, asset_id, seller_attested, db)
        elif decision == "regenerate":
            if target is not None:
                candidates = [target] if target.status in FAILED_STATUSES | REVIEWABLE_STATUSES else []
            else:
                candidates = [job for job in latest if job.status in FAILED_STATUSES]
            if not candidates:
                raise ImageGenerationGateError("NO_FAILED_SCENES", "재시도할 실패·차단·거절 장면이 없습니다.")
            result = _summary(_owned_jobs(project_id, run_id, db))
            scene_ids = [str(job.scene_id or job.section_id) for job in candidates]
            result["regenerate_scene_ids"] = scene_ids
            result["scene_attempts"] = _next_attempts(rows, scene_ids)
            result["next_action"] = "cost_approval"
            return result
        else:
            raise ImageGenerationGateError("IMAGE_REVIEW_DECISION_INVALID", "지원하지 않는 이미지 검수 결정입니다.")
    except StoryboardImageGenerationError as error:
        raise ImageGenerationGateError("IMAGE_REVIEW_FAILED", str(error)) from error
    result = _summary(_owned_jobs(project_id, run_id, db))
    if result["all_required_scenes_approved"]:
        result["approved_asset_manifest"] = build_approved_asset_manifest(
            run_id=run_id,
            project_id=project_id,
            db=db,
        )
    result["next_action"] = "finalize" if result["all_required_scenes_approved"] else "review"
    return result
