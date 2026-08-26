"""LG-5R database outbox worker and recovery sweep.

The outbox is the durable boundary. The optional FastAPI poller and a separate
worker process both call the same lease-based functions; neither owns state in
memory. A paid request whose process outcome is unknown is dead-lettered
instead of being dispatched a second time.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import logging
import os
import socket
import uuid
from typing import Any

from sqlalchemy.orm import Session

from src.config import settings
from src.db.models import AgentRun, ImageGenerationJobRecord, ImageGenerationOutboxRecord
from src.services.image_generation_provider import ImageGenerationRequest, ImageGenerationResult
from src.services.image_generation_service import execute_image_generation


logger = logging.getLogger(__name__)
RETRYABLE_CODES = {"PROVIDER_TIMEOUT"}


def normalize_image_error(error: Exception | str | None, fallback_code: str = "PROVIDER_ERROR") -> tuple[str, str, str]:
    raw = " ".join(str(error or "").split())[:500]
    lowered = raw.lower()
    code = raw.split(":", 1)[0].strip().upper() if ":" in raw else fallback_code
    if any(token in lowered for token in ("api key", "not configured", "invalid_api_key", "authentication")):
        return "API_KEY_MISSING", raw, "API 키를 확인한 뒤 같은 실행을 재개해 주세요."
    if any(token in lowered for token in ("billing", "hard_limit", "insufficient_quota", "balance", "credit", "rate_limit")):
        return "BALANCE_OR_LIMIT", raw, "API 잔액·사용 한도를 확인한 뒤 실패 장면만 다시 시도해 주세요."
    if "timeout" in lowered or code == "TIMEOUT":
        return "PROVIDER_TIMEOUT", raw, "제공자 응답 시간이 초과되었습니다. 실패 장면만 다시 시도할 수 있습니다."
    if any(token in lowered for token in ("moderation", "safety", "policy", "unsafe")):
        return "PROVIDER_SAFETY", raw, "제공자 안전 정책에 의해 차단되었습니다. 장면 요청을 수정해 주세요."
    if any(token in lowered for token in ("identity", "silhouette", "product structure")):
        return "IDENTITY_MISMATCH", raw, "상품 외형이 기준 사진과 일치하지 않아 차단했습니다. 기준 사진을 확인해 주세요."
    if any(token in lowered for token in ("ocr", "foreign_text", "supplier_text", "watermark", "qr")):
        return "OCR_CONTAMINATION", raw, "생성 이미지에서 글자·워터마크·QR 오염이 발견되었습니다."
    if any(token in lowered for token in ("rights", "license", "reference_final_output", "seller_owned")):
        return "RIGHTS_BLOCKED", raw, "사용 권리가 확인된 사진만 기준 또는 최종 이미지로 선택해 주세요."
    aliases = {
        "BILLING_HARD_LIMIT_REACHED": "BALANCE_OR_LIMIT",
        "MODERATION_REJECTED": "PROVIDER_SAFETY",
        "IDENTITY_GATE_REJECTED": "IDENTITY_MISMATCH",
        "UNSAFE_GENERATED_CONTENT_DETECTED": "OCR_CONTAMINATION",
        "SUPPLIER_REFERENCE_FINAL_OUTPUT_BLOCKED": "RIGHTS_BLOCKED",
    }
    normalized = aliases.get(code, code if code and code != "PROVIDER_ERROR" else fallback_code)
    actions = {
        "BALANCE_OR_LIMIT": "API 잔액·사용 한도를 확인한 뒤 실패 장면만 다시 시도해 주세요.",
        "PROVIDER_SAFETY": "제공자 안전 정책에 맞게 장면 요청을 수정해 주세요.",
        "IDENTITY_MISMATCH": "상품 외형과 기준 사진을 확인해 주세요.",
        "OCR_CONTAMINATION": "글자·로고 없는 장면으로 다시 생성해 주세요.",
        "RIGHTS_BLOCKED": "권리가 확인된 사진을 선택해 주세요.",
    }
    return normalized, raw, actions.get(normalized, "오류 원인을 확인한 뒤 실패 장면만 다시 시도해 주세요.")


class DurableFakeImageProvider:
    """Zero-cost provider used by the full worker/checkpoint E2E."""

    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        from io import BytesIO
        from PIL import Image, ImageDraw

        # Keep the product silhouette/color family while deliberately changing
        # the commercial composition. This lets the normal identity validator
        # prove both preservation and non-reproduction in the fake-provider E2E.
        image = Image.new("RGB", (512, 512), color=(224, 232, 238))
        draw = ImageDraw.Draw(image)
        draw.ellipse((188, 116, 324, 228), fill=(138, 148, 158))
        draw.rounded_rectangle((112, 210, 400, 354), radius=44, fill=(128, 139, 150))
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return ImageGenerationResult(
            content=buffer.getvalue(),
            mime_type="image/png",
            provider="fake_provider",
            model="fake-image-lg5r-v1",
            usage_metadata={"actual_cost": 0.0, "fake_provider": True},
        )


def worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _record_hash(identifier: str, key: str | None) -> str:
    return key if isinstance(key, str) and len(key) == 64 else hashlib.sha256(identifier.encode("utf-8")).hexdigest()


def _append_recovery_event(
    run: AgentRun,
    delivery: ImageGenerationOutboxRecord,
    job: ImageGenerationJobRecord,
    db: Session,
    *,
    event_type: str,
    reason_code: str,
) -> None:
    from src.services.langgraph_run_service import AgentRunEventJournal

    AgentRunEventJournal.append_recovery_event(
        run,
        db,
        event_type=event_type,
        job_id=job.id,
        job_key=_record_hash(job.id, job.idempotency_key),
        outbox_id=delivery.id,
        outbox_key=_record_hash(delivery.id, delivery.idempotency_key),
        attempt=int(delivery.delivery_attempts or 0),
        retry_state=str(delivery.status),
        reason_code=reason_code,
    )


def _append_delivery_timing(
    run: AgentRun,
    delivery: ImageGenerationOutboxRecord,
    db: Session,
    *,
    event_type: str,
) -> None:
    from src.services.langgraph_run_service import AgentRunEventJournal

    AgentRunEventJournal.append_timing_event(
        run,
        db,
        event_type=event_type,
        timing={
            "outbox": {"id": delivery.id, "version": 1, "hash": _record_hash(delivery.id, delivery.idempotency_key)},
            "attempt": int(delivery.delivery_attempts or 0),
        },
    )


def _scoped_delivery(
    delivery: ImageGenerationOutboxRecord,
    db: Session,
) -> tuple[AgentRun, ImageGenerationJobRecord] | None:
    """Accept provider work only when its persisted ownership tuple agrees."""

    run = db.query(AgentRun).filter(AgentRun.id == delivery.run_id).first()
    job = db.query(ImageGenerationJobRecord).filter(ImageGenerationJobRecord.id == delivery.image_job_id).first()
    expected_thread = (run.graph_thread_id or run.id) if run is not None else ""
    matches = bool(
        run is not None
        and job is not None
        and delivery.workspace_id == run.workspace_id
        and delivery.project_id == run.project_id == job.project_id
        and delivery.thread_id == expected_thread
        and delivery.job_id == job.job_id
        and delivery.idempotency_key == job.idempotency_key
    )
    if matches:
        return run, job
    if run is not None and job is not None:
        _append_recovery_event(
            run,
            delivery,
            job,
            db,
            event_type="stale_delivery_blocked",
            reason_code="SCOPE_TUPLE_MISMATCH",
        )
    logger.warning("Blocked image delivery %s because its persisted scope tuple is inconsistent", delivery.id)
    return None


def recover_expired_image_work(
    db: Session, *, now: datetime.datetime | None = None, workspace_id: str | None = None
) -> dict[str, int]:
    now = now or datetime.datetime.utcnow()
    recovered = 0
    dead_lettered = 0
    query = db.query(ImageGenerationOutboxRecord).filter(
        ImageGenerationOutboxRecord.status == "leased",
        ImageGenerationOutboxRecord.lease_expires_at.isnot(None),
        ImageGenerationOutboxRecord.lease_expires_at <= now,
    )
    if workspace_id:
        query = query.filter(ImageGenerationOutboxRecord.workspace_id == workspace_id)
    expired = query.all()
    for delivery in expired:
        scoped = _scoped_delivery(delivery, db)
        if scoped is None:
            continue
        run, job = scoped
        # Fake work is free and deterministic. A paid synchronous request that
        # died after dispatch has an unknowable billing outcome, so retrying it
        # would violate OPS-03; an operator must reconcile it first.
        if delivery.provider_mode != "mock" and delivery.provider_dispatch_count > 0:
            delivery.status = "dead_letter"
            delivery.dead_lettered_at = now
            delivery.last_error_code = "PROVIDER_OUTCOME_UNKNOWN"
            delivery.last_error_message = "유료 provider 전송 뒤 결과가 확인되지 않아 중복 비용 방지를 위해 자동 재전송하지 않았습니다."
            if job.status in {"running", "generating", "queued"}:
                job.status = "failed"
                job.error_code = "PROVIDER_OUTCOME_UNKNOWN"
                job.warnings = [delivery.last_error_message]
            from src.services.image_generation_service import record_unknown_provider_attempt_for_delivery
            record_unknown_provider_attempt_for_delivery(job, db, outcome_code="PROVIDER_OUTCOME_UNKNOWN")
            _append_recovery_event(
                run,
                delivery,
                job,
                db,
                event_type="lease_expired_provider_outcome_unknown",
                reason_code="PROVIDER_OUTCOME_UNKNOWN",
            )
            dead_lettered += 1
        else:
            delivery.status = "queued"
            delivery.available_at = now
            delivery.lease_owner = None
            delivery.lease_expires_at = None
            if job.status in {"running", "generating"}:
                job.status = "queued"
            _append_recovery_event(
                run,
                delivery,
                job,
                db,
                event_type="lease_expired_requeued",
                reason_code="LEASE_EXPIRED",
            )
            recovered += 1
    db.commit()
    return {"recovered": recovered, "dead_lettered": dead_lettered}


def claim_image_delivery(
    db: Session, *, owner: str, lease_seconds: int | None = None, now: datetime.datetime | None = None
) -> ImageGenerationOutboxRecord | None:
    now = now or datetime.datetime.utcnow()
    lease_seconds = lease_seconds or settings.SELLFORM_IMAGE_WORKER_LEASE_SECONDS
    recover_expired_image_work(db, now=now)
    candidates = db.query(ImageGenerationOutboxRecord).filter(
        ImageGenerationOutboxRecord.status.in_(["queued", "retry_wait"]),
        ImageGenerationOutboxRecord.available_at <= now,
    ).order_by(ImageGenerationOutboxRecord.created_at.asc()).limit(10).all()
    for candidate in candidates:
        if _scoped_delivery(candidate, db) is None:
            db.commit()
            continue
        claimed = db.query(ImageGenerationOutboxRecord).filter(
            ImageGenerationOutboxRecord.id == candidate.id,
            ImageGenerationOutboxRecord.status.in_(["queued", "retry_wait"]),
        ).update(
            {
                ImageGenerationOutboxRecord.status: "leased",
                ImageGenerationOutboxRecord.lease_owner: owner,
                ImageGenerationOutboxRecord.lease_expires_at: now + datetime.timedelta(seconds=lease_seconds),
                ImageGenerationOutboxRecord.delivery_attempts: candidate.delivery_attempts + 1,
            },
            synchronize_session=False,
        )
        if claimed == 1:
            delivery = db.query(ImageGenerationOutboxRecord).filter(ImageGenerationOutboxRecord.id == candidate.id).one()
            scoped = _scoped_delivery(delivery, db)
            if scoped is not None:
                _append_delivery_timing(scoped[0], delivery, db, event_type="delivery_leased")
            db.commit()
            return delivery
        db.rollback()
    return None


def _review_stage(run: AgentRun | None) -> str:
    if run is None:
        return ""
    pending = ((run.outputs_json or {}).get("langgraph_review") or {}).get("pending") or {}
    return str(pending.get("review_stage") or "")


def _resume_completed_run(run_id: str) -> AgentRun | None:
    try:
        from src.services.langgraph_run_service import LangGraphRunService

        return LangGraphRunService.resume_provider_wait(run_id)
    except Exception:
        logger.error("Could not resume LangGraph provider wait for run %s", run_id)
        return None


def _provider_wait_is_ready(run: AgentRun, db: Session) -> tuple[bool, dict[str, Any]]:
    """Return whether the current generation wave has no unfinished scene.

    Readiness is derived from the latest attempt for every scene.  A failed or
    blocked terminal job must still release ``provider_wait`` so the seller can
    review/retry it; only queued/running work keeps the graph interrupted.
    """

    if run.status != "awaiting_review" or _review_stage(run) != "provider_wait":
        return False, {}
    _recover_completed_delivery_results(run.id, db)
    from src.services.langgraph_image_generation_service import collect_graph_image_results

    try:
        summary = collect_graph_image_results(run_id=run.id, project_id=run.project_id, db=db)
    except Exception:
        logger.error("Could not collect image generation readiness for run %s", run.id)
        return False, {}
    return int(summary.get("pending_count") or 0) == 0, summary


def _recover_completed_delivery_results(run_id: str, db: Session) -> None:
    """Repair a crash-window row before deciding whether a graph wait is ready.

    A provider delivery can be durably marked completed after the generated
    asset is saved, while its job row remains in a pending status if that
    process is interrupted before its final state is observed.  Treat only
    the newest attempt for each scene as recoverable and never redispatch it:
    the existing output asset makes it a seller-review candidate.
    """

    rows = (
        db.query(ImageGenerationJobRecord, ImageGenerationOutboxRecord)
        .join(ImageGenerationOutboxRecord, ImageGenerationOutboxRecord.image_job_id == ImageGenerationJobRecord.id)
        .filter(ImageGenerationOutboxRecord.run_id == run_id)
        .order_by(ImageGenerationJobRecord.created_at.asc(), ImageGenerationJobRecord.job_id.asc())
        .all()
    )
    latest: dict[str, tuple[ImageGenerationJobRecord, ImageGenerationOutboxRecord]] = {}
    for job, delivery in rows:
        scene_id = str(job.scene_id or job.section_id)
        current = latest.get(scene_id)
        if current is None or int(job.generation_attempt or 1) > int(current[0].generation_attempt or 1):
            latest[scene_id] = (job, delivery)

    recovered = False
    for job, delivery in latest.values():
        if _scoped_delivery(delivery, db) is None:
            continue
        if (
            delivery.status == "completed"
            and job.status in {"queued", "leased", "running", "generating"}
            and job.output_asset_id
        ):
            validation = dict(job.validation_result or {})
            job.status = "blocked" if validation.get("status") == "blocked" else "needs_review"
            recovered = True
    if recovered:
        db.commit()


def _mark_generation_wave_resumed(run_id: str, job_ids: list[str], db: Session) -> None:
    """Persist one audit marker for the completed latest-attempt wave.

    This marker is deliberately not a resume lock.  The durable AgentRun
    status transition owns exactly-once execution, so a process crash after a
    job commit can always be reconciled without an audit flag suppressing it.
    """

    if not job_ids:
        return
    candidates = (
        db.query(ImageGenerationOutboxRecord)
        .filter(
            ImageGenerationOutboxRecord.run_id == run_id,
            ImageGenerationOutboxRecord.job_id.in_(job_ids),
            ImageGenerationOutboxRecord.status.in_(["completed", "dead_letter"]),
            ImageGenerationOutboxRecord.completion_resume_count == 0,
        )
        .order_by(
            ImageGenerationOutboxRecord.completed_at.desc(),
            ImageGenerationOutboxRecord.created_at.desc(),
        )
        .all()
    )
    for candidate in candidates:
        claimed = (
            db.query(ImageGenerationOutboxRecord)
            .filter(
                ImageGenerationOutboxRecord.id == candidate.id,
                ImageGenerationOutboxRecord.completion_resume_count == 0,
            )
            .update(
                {ImageGenerationOutboxRecord.completion_resume_count: 1},
                synchronize_session=False,
            )
        )
        db.commit()
        if claimed == 1:
            return


def _resume_provider_wait_if_ready(run_id: str, db: Session, *, recovery: bool = False) -> bool:
    run = (
        db.query(AgentRun)
        .filter(AgentRun.id == run_id)
        .populate_existing()
        .first()
    )
    ready, summary = _provider_wait_is_ready(run, db) if run is not None else (False, {})
    if not ready:
        return False
    # Reconciliation can have taken the AgentRun journal's FOR UPDATE lock
    # while absorbing an already-recorded provider-cost event.  The resume
    # lease uses a separate SessionLocal, so finish this worker-owned unit of
    # work before trying to acquire that same AgentRun row again.
    db.commit()
    resumed = _resume_completed_run(run_id)
    if resumed is None:
        return False
    # A competing worker may have acquired the AgentRun lease and still be
    # executing.  Only the caller that observes the persisted stage advance
    # records this wave's completion callback.
    if resumed.status == "awaiting_review" and _review_stage(resumed) == "provider_wait":
        return False
    if resumed.status == "running" and resumed.current_stage == "provider_wait":
        return False
    if recovery:
        delivery = (
            db.query(ImageGenerationOutboxRecord)
            .filter(
                ImageGenerationOutboxRecord.run_id == run_id,
                ImageGenerationOutboxRecord.job_id.in_(list(summary.get("job_ids") or [])),
                ImageGenerationOutboxRecord.status.in_(["completed", "dead_letter"]),
                ImageGenerationOutboxRecord.completion_resume_count == 0,
            )
            .order_by(ImageGenerationOutboxRecord.completed_at.desc(), ImageGenerationOutboxRecord.created_at.desc())
            .first()
        )
        if delivery is not None:
            scoped = _scoped_delivery(delivery, db)
            if scoped is not None:
                _append_recovery_event(
                    resumed,
                    delivery,
                    scoped[1],
                    db,
                    event_type="provider_wait_reconciled",
                    reason_code="PROVIDER_WAIT_RECONCILED",
                )
    _mark_generation_wave_resumed(run_id, list(summary.get("job_ids") or []), db)
    return True


def reconcile_ready_provider_wait_runs(db: Session) -> list[str]:
    """Recover the last-job-commit/callback crash window from durable state."""

    run_ids = [
        row[0]
        for row in db.query(AgentRun.id)
        .filter(AgentRun.status == "awaiting_review")
        .order_by(AgentRun.updated_at.asc())
        .all()
    ]
    resumed: list[str] = []
    for run_id in run_ids:
        from src.services.image_generation_service import reconcile_provider_cost_projection
        if reconcile_provider_cost_projection(run_id, db):
            db.commit()
        if _resume_provider_wait_if_ready(run_id, db, recovery=True):
            resumed.append(run_id)
    return resumed


def process_image_delivery(delivery_id: str, owner: str, db: Session) -> dict[str, Any]:
    delivery = db.query(ImageGenerationOutboxRecord).filter(
        ImageGenerationOutboxRecord.id == delivery_id,
        ImageGenerationOutboxRecord.status == "leased",
        ImageGenerationOutboxRecord.lease_owner == owner,
    ).first()
    if delivery is None:
        return {"status": "not_owned"}
    scoped = _scoped_delivery(delivery, db)
    if scoped is None:
        db.commit()
        return {"status": "stale_delivery_blocked"}
    run, job = scoped
    # A completion committed before a worker crash makes redelivery a read.
    if job.status in {"needs_review", "approved", "blocked", "rejected", "failed"} and job.output_asset_id:
        delivery.status = "completed"
        delivery.completed_at = datetime.datetime.utcnow()
        delivery.lease_owner = None
        delivery.lease_expires_at = None
        db.commit()
        _resume_provider_wait_if_ready(delivery.run_id, db)
        return {"status": "completed", "job_id": job.job_id, "deduplicated": True}

    delivery.provider_dispatch_count += 1
    job.status = "running"
    db.add_all([delivery, job])
    db.commit()
    try:
        provider = DurableFakeImageProvider() if delivery.provider_mode == "mock" else None
        result = execute_image_generation(
            delivery.project_id,
            delivery.job_id,
            db,
            cost_approved=True,
            provider_override=provider,
        )
        if result.error_code:
            code, detail, action = normalize_image_error(result.error_code, result.error_code)
            result.error_code = code
            result.warnings = [*(result.warnings or []), action]
        delivery.status = "completed"
        delivery.completed_at = datetime.datetime.utcnow()
        delivery.lease_owner = None
        delivery.lease_expires_at = None
        delivery.last_error_code = result.error_code
        delivery.last_error_message = (result.warnings or [None])[0]
        db.add_all([delivery, result])
        db.commit()
    except Exception as error:
        code, detail, action = normalize_image_error(error)
        job = db.query(ImageGenerationJobRecord).filter(ImageGenerationJobRecord.id == delivery.image_job_id).one()
        delivery = db.query(ImageGenerationOutboxRecord).filter(ImageGenerationOutboxRecord.id == delivery_id).one()
        delivery.last_error_code = code
        delivery.last_error_message = action
        delivery.lease_owner = None
        delivery.lease_expires_at = None
        job.error_code = code
        job.warnings = [action, *(job.warnings or [])]
        # A paid request that timed out may already have been billed. Never
        # redispatch it automatically; the seller can create a new, explicitly
        # cost-approved scene attempt after reconciliation. Free deterministic
        # fake work may be retried safely for E2E/recovery testing.
        if (
            code in RETRYABLE_CODES
            and delivery.provider_mode == "mock"
            and delivery.delivery_attempts < delivery.max_delivery_attempts
        ):
            delivery.status = "retry_wait"
            delivery.available_at = datetime.datetime.utcnow()
            job.status = "queued"
            _append_delivery_timing(run, delivery, db, event_type="retry_scheduled")
        else:
            delivery.status = "dead_letter"
            delivery.dead_lettered_at = datetime.datetime.utcnow()
            job.status = "failed"
        db.add_all([delivery, job])
        db.commit()
    if delivery.status in {"completed", "dead_letter"}:
        _resume_provider_wait_if_ready(delivery.run_id, db)
    return {
        "status": delivery.status,
        "job_id": delivery.job_id,
        "error_code": delivery.last_error_code,
        "provider_dispatch_count": delivery.provider_dispatch_count,
    }


def run_image_worker_batch(
    db: Session, *, owner: str | None = None, batch_size: int | None = None
) -> list[dict[str, Any]]:
    owner = owner or worker_identity()
    batch_size = batch_size or settings.SELLFORM_IMAGE_WORKER_BATCH_SIZE
    results: list[dict[str, Any]] = []
    # This also runs when there is no queued delivery.  It repairs a process
    # crash after the final job commit but before the graph resume callback.
    reconcile_ready_provider_wait_runs(db)
    for _ in range(batch_size):
        delivery = claim_image_delivery(db, owner=owner)
        if delivery is None:
            break
        results.append(process_image_delivery(delivery.id, owner, db))
    reconcile_ready_provider_wait_runs(db)
    return results


def retry_dead_letter(delivery_id: str, db: Session) -> ImageGenerationOutboxRecord:
    delivery = db.query(ImageGenerationOutboxRecord).filter(ImageGenerationOutboxRecord.id == delivery_id).with_for_update().first()
    if delivery is None:
        raise ValueError("이미지 worker 작업을 찾을 수 없습니다.")
    if delivery.status != "dead_letter":
        raise ValueError("dead-letter 작업만 운영자가 다시 시도할 수 있습니다.")
    scoped = _scoped_delivery(delivery, db)
    if scoped is None:
        db.commit()
        raise ValueError("작업의 저장된 범위가 일치하지 않아 재시도할 수 없습니다.")
    # Real-provider deliveries may already have incurred a charge even when
    # the provider returned a concrete error. They must return through
    # scene-level cost approval or a seller-owned upload instead of bypassing
    # that gate through the worker retry endpoint.
    if delivery.provider_mode != "mock":
        raise ValueError("유료 provider 작업은 worker 재시도를 지원하지 않습니다. 장면 재생성 또는 판매자 사진 업로드를 사용해 주세요.")
    delivery.status = "queued"
    delivery.available_at = datetime.datetime.utcnow()
    delivery.dead_lettered_at = None
    delivery.lease_owner = None
    delivery.lease_expires_at = None
    delivery.image_job.status = "queued"
    _append_recovery_event(
        scoped[0],
        delivery,
        scoped[1],
        db,
        event_type="dead_letter_requeue",
        reason_code="OPERATOR_REQUEUE",
    )
    db.commit()
    return delivery


async def image_worker_poller(stop_event: asyncio.Event) -> None:
    """Cancellable app poller; DB state survives this task and the process."""

    from src.db.database import SessionLocal

    owner = worker_identity()
    while not stop_event.is_set():
        db = SessionLocal()
        try:
            await asyncio.to_thread(run_image_worker_batch, db, owner=owner)
        except Exception:
            logger.error("LG-5R image worker poll failed")
        finally:
            db.close()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.SELLFORM_IMAGE_WORKER_POLL_SECONDS)
        except asyncio.TimeoutError:
            pass


def run_worker_forever() -> None:
    """Entry point for a dedicated worker process."""

    import time
    from src.db.database import SessionLocal

    owner = worker_identity()
    while True:
        db = SessionLocal()
        try:
            run_image_worker_batch(db, owner=owner)
        finally:
            db.close()
        time.sleep(settings.SELLFORM_IMAGE_WORKER_POLL_SECONDS)


if __name__ == "__main__":
    run_worker_forever()
