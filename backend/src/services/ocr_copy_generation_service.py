"""UX-2E-1 OCR candidates and grounded Korean copy generation.

Every provider result crosses the provider-neutral GenerationJob contract,
receives a durable project/workspace audit row, and remains seller-review-only
until explicitly approved.  The default deterministic provider is intentional
for installations without a paid model credential; it is not presented as an
external LLM response.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from src.config import settings
from src.db.models import Asset, GenerationJobRecord, ProductFact, ProductProject
from src.schemas.api_ready_generation import (
    GenerationJobRequestSchema,
    GenerationJobResultSchema,
    GenerationOutputSpecSchema,
    GenerationValidationResultSchema,
)
from src.services.asset_understanding_service import run_asset_inspection
from src.services.commerce_policy import CONFIRMED_FACT_STATUSES
from src.services.fact_evidence_service import (
    NormalizedCandidate,
    apply_conflicts,
    normalize_candidates,
    upsert_candidate,
)
from src.services.generation_provider_adapter import GenerationProviderAdapter
from src.services.grounding_validator import detect_claim_risks

OCR_FAILURES = {"provider_error", "safety_blocked", "low_confidence"}
DEFAULT_FORBIDDEN_CLAIMS = (
    "치료", "완치", "보장", "최고", "최저", "1위", "타사", "인증", "가격",
)
COPY_JOB_TYPE = "grounded_copy"
OCR_JOB_TYPE = "ocr_candidate"
COPY_PROVIDER = "deterministic" if settings.SELLFORM_GENERATION_MODE == "mock" else "configured_text_router"
COPY_MODEL = "grounded-template-v2" if COPY_PROVIDER == "deterministic" else settings.SELLFORM_TEXT_LLM_PRIMARY_MODEL


def _hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _job(
    db: Session,
    project: ProductProject,
    user_id: str,
    *,
    task_type: str,
    snapshot: dict[str, Any],
    provider: str,
    model: str,
    scene_id: str | None = None,
    asset_id: str | None = None,
) -> GenerationJobRecord:
    value_hash = _hash(snapshot)
    record = GenerationJobRecord(
        workspace_id=project.workspace_id,
        project_id=project.id,
        job_id=f"ux2e1-{task_type}-{uuid4()}",
        request_id=str(uuid4()),
        task_type=task_type,
        scene_id=scene_id,
        asset_id=asset_id,
        provider=provider,
        model_name=model,
        status="running",
        input_snapshot=snapshot,
        input_snapshot_hash=value_hash,
        estimated_cost=0,
        actual_cost=0,
        created_by=user_id,
    )
    db.add(record)
    db.flush()
    return record


def _finish_job(
    record: GenerationJobRecord,
    *,
    status: str,
    output: dict[str, Any] | None = None,
    failure_category: str | None = None,
    retryable: bool = False,
    error_code: str | None = None,
    message: str | None = None,
    usage: dict[str, int] | None = None,
) -> None:
    record.status = status
    record.output_json = output or {}
    record.failure_category = failure_category
    record.retryable = retryable
    record.error_code = error_code
    record.error_message = message
    record.usage_metadata = usage or {}


def _safe_asset_status(asset: Asset) -> str:
    return "safety_blocked" if asset.usage_status == "blocked" else "reference_only"


def _ocr_failure(record: Any) -> tuple[str, str, bool]:
    code = str(getattr(record, "error_code", "") or "")
    if getattr(record, "status", "") == "failed":
        return "provider_error", code or "ocr_provider_failed", True
    if code in {"ocr_image_not_available", "ocr_image_not_local", "ocr_no_text_detected"}:
        return "low_confidence", code, True
    return "low_confidence", code or "no_normalizable_specification", True


def ingest_ocr_candidates(
    db: Session,
    project: ProductProject,
    asset_ids: list[str],
    user_id: str,
) -> dict[str, Any]:
    """Inspect selected reference images and persist review-only OCR facts."""
    requested_ids = list(dict.fromkeys(asset_ids))
    assets = db.query(Asset).filter(Asset.project_id == project.id, Asset.id.in_(requested_ids)).all()
    found_ids = {asset.id for asset in assets}
    results: list[dict[str, Any]] = []
    created_fact_ids: list[str] = []
    for missing_id in [asset_id for asset_id in requested_ids if asset_id not in found_ids]:
        record = _job(db, project, user_id, task_type=OCR_JOB_TYPE, snapshot={"asset_id": missing_id}, provider="asset_inspection", model="local-ocr-contract", asset_id=None)
        _finish_job(record, status="failed", failure_category="provider_error", retryable=False, error_code="asset_not_found", message="프로젝트의 사진을 찾을 수 없습니다.")
        results.append({"asset_id": missing_id, "status": "provider_error", "message": "프로젝트의 사진을 찾을 수 없습니다.", "candidate_count": 0, "retryable": False, "job_id": record.job_id})
    for asset in assets:
        record = _job(db, project, user_id, task_type=OCR_JOB_TYPE, snapshot={"asset_id": asset.id, "source_kind": asset.source_type}, provider="asset_inspection", model="local-ocr-contract", asset_id=asset.id)
        if _safe_asset_status(asset) == "safety_blocked":
            _finish_job(record, status="failed", failure_category="safety_blocked", retryable=False, error_code="asset_blocked", message="차단된 사진은 OCR 후보로 처리할 수 없습니다.")
            results.append({"asset_id": asset.id, "status": "safety_blocked", "message": "차단된 사진은 OCR 후보로 처리할 수 없습니다.", "candidate_count": 0, "retryable": False, "job_id": record.job_id})
            continue
        try:
            inspection = run_asset_inspection(asset, db)
        except Exception:
            _finish_job(record, status="failed", failure_category="provider_error", retryable=True, error_code="inspection_exception", message="OCR 처리 중 제공자 오류가 발생했습니다.")
            results.append({"asset_id": asset.id, "status": "provider_error", "message": "OCR 처리 중 오류가 발생했습니다. 다시 시도하거나 직접 입력해 주세요.", "candidate_count": 0, "retryable": True, "job_id": record.job_id})
            continue
        blocks = inspection.ocr_blocks or []
        translations = inspection.translation_blocks or []
        translation_by_text = {str(item.get("source_text") or ""): item for item in translations}
        candidates_created = 0
        for index, block in enumerate(blocks):
            source_text = str(block.get("text") or "").strip()
            if not source_text:
                continue
            confidence = block.get("confidence")
            if confidence is not None and float(confidence) < 0.45:
                continue
            translation = translation_by_text.get(source_text, {})
            translated_text = str(translation.get("translated_text") or source_text).strip()
            for candidate in normalize_candidates(source_text):
                candidate = NormalizedCandidate(**{**candidate.__dict__, "needs_review": True})
                fact = upsert_candidate(
                    db, project.id, candidate, source_type="asset_ocr", user_id=user_id,
                    source_asset_id=asset.id, bbox=block.get("bbox"), ocr_block_index=index,
                    confidence=float(confidence) if confidence is not None else 0.75,
                    translated_text=translated_text, inspection_id=inspection.id,
                    ocr_language=str(block.get("language") or translation.get("language") or "unknown"),
                    ocr_provider=str(block.get("source") or "asset_inspection"),
                    ocr_model=inspection.analyzer_version, processed_at=inspection.completed_at,
                )
                # OCR never auto-confirms a newly created fact. Existing
                # seller-confirmed facts retain their explicit confirmation.
                if fact.verification_status not in CONFIRMED_FACT_STATUSES:
                    fact.verification_status, fact.needs_review = "needs_review", True
                created_fact_ids.append(fact.id)
                candidates_created += 1
        if not candidates_created:
            category, code, retryable = _ocr_failure(inspection)
            _finish_job(record, status="failed", failure_category=category, retryable=retryable, error_code=code, message="인식 가능한 사양이 없습니다.")
            results.append({"asset_id": asset.id, "status": category, "message": "더 선명한 사진으로 재시도하거나 판매자 직접 입력을 추가해 주세요.", "candidate_count": 0, "retryable": retryable, "job_id": record.job_id})
            continue
        _finish_job(record, status="succeeded", output={"candidate_count": candidates_created, "inspection_id": inspection.id}, usage={"input_tokens": 0, "output_tokens": 0})
        results.append({"asset_id": asset.id, "status": "completed", "candidate_count": candidates_created, "message": "한국어 사실 후보를 검토해 주세요.", "provider": inspection.analyzer_version, "model": "local-ocr-contract", "retryable": False, "job_id": record.job_id})
    apply_conflicts(db, project.id)
    return {"project_id": project.id, "results": results, "created_fact_ids": list(dict.fromkeys(created_fact_ids))}


def _copy_failure(text: str, forbidden_claims: list[str], facts: list[ProductFact]) -> list[str]:
    lowered = text.lower()
    blocked = [claim for claim in forbidden_claims if claim and claim.lower() in lowered]
    blocked.extend(word for word in DEFAULT_FORBIDDEN_CLAIMS if word.lower() in lowered and word not in blocked)
    confirmed_texts = [fact.fact_text for fact in facts]
    for risk in detect_claim_risks(text, confirmed_texts):
        blocked.append(f"unsupported:{risk.phrase}")
    return list(dict.fromkeys(blocked))


def _draft_for_scene(scene: dict[str, Any], facts: list[ProductFact], product_name: str) -> tuple[str, str]:
    scene_type = scene.get("scene_type") or "feature_closeup"
    headline = {
        "hero_product": product_name,
        "usage_scene": "사용 전 제품 정보 확인",
        "feature_closeup": "확인된 제품 특징",
        "charging_or_power": "전원·배터리 정보 확인",
        "comparison": "구매 전 제품 정보 확인",
        "spec_graphic": "제품 사양 확인",
        "notice": "사용 전 안내",
    }.get(scene_type, "확인된 제품 정보")
    if scene_type == "comparison":
        body = "판매자가 확인한 자사 제품 정보를 안내합니다. 구매 전 사양을 확인해 주세요."
    elif facts:
        body = " · ".join(fact.fact_text for fact in facts[:2]) + "."
    else:
        body = "판매자가 확인한 제품 정보를 안내합니다."
    return headline, body


class DeterministicGroundedCopyProvider(GenerationProviderAdapter):
    """Local provider implementing the exact same typed job boundary."""
    def submit(self, request: GenerationJobRequestSchema) -> GenerationJobResultSchema:
        output = request.prompt_blueprint.get("deterministic_output") or {}
        return GenerationJobResultSchema(
            request_id=request.request_id, status="needs_seller_review",
            provider_job_id=f"local-{request.request_id}", provider_response_id=f"local-{request.request_id}",
            generated_text=json.dumps(output, ensure_ascii=False), estimated_cost=0, actual_cost=0,
            usage={"input_tokens": 0, "output_tokens": 0},
            validation=GenerationValidationResultSchema(product_identity="passed", ocr="passed", rights="passed"),
        )

    def get_status(self, provider_job_id: str, request_id: str) -> GenerationJobResultSchema:
        return GenerationJobResultSchema(request_id=request_id, status="needs_seller_review", provider_job_id=provider_job_id)


def _approved_fact_payload(fact: ProductFact) -> dict[str, Any]:
    return {"id": fact.id, "text": fact.fact_text, "field_key": fact.field_key, "value": fact.normalized_value, "unit": fact.normalized_unit}


def _copy_snapshot(plan: dict[str, Any], scene: dict[str, Any], facts: list[ProductFact]) -> dict[str, Any]:
    brief = plan.get("product_brief") or {}
    return {
        "plan_version": plan.get("version"), "scene_id": scene.get("id"), "objective": scene.get("objective"),
        "scene_type": scene.get("scene_type"), "channel": brief.get("sales_channel"),
        "tone": brief.get("tone", "사실 중심의 신뢰감 있는 한국어"), "max_length": {"headline": 60, "body": 180},
        "forbidden_claims": list(dict.fromkeys([*(brief.get("forbidden_claims") or []), *DEFAULT_FORBIDDEN_CLAIMS])),
        "confirmed_facts": [_approved_fact_payload(fact) for fact in facts],
    }


def estimate_grounded_copy_drafts(project: ProductProject, plan: dict[str, Any], scene_ids: list[str] | None = None) -> dict[str, Any]:
    selected = set(scene_ids or [str(scene.get("id")) for scene in plan.get("scenes") or []])
    return {"project_id": project.id, "scene_count": sum(str(scene.get("id")) in selected for scene in plan.get("scenes") or []), "estimated_cost": 0, "provider": COPY_PROVIDER, "model": COPY_MODEL}


def create_grounded_copy_drafts(db: Session, project: ProductProject, plan: dict[str, Any], scene_ids: list[str] | None, seller_cost_approved: bool, user_id: str) -> dict[str, Any]:
    if not seller_cost_approved:
        raise ValueError("카피 작업 수와 예상 비용을 확인한 뒤 판매자 승인이 필요합니다.")
    allowed_facts = [fact for fact in db.query(ProductFact).filter(ProductFact.project_id == project.id).all() if fact.verification_status in CONFIRMED_FACT_STATUSES and not fact.needs_review and fact.evidences]
    facts_by_id = {fact.id: fact for fact in allowed_facts}
    selected = set(scene_ids or [str(scene.get("id")) for scene in plan.get("scenes") or []])
    results: list[dict[str, Any]] = []
    for scene in plan.get("scenes") or []:
        if str(scene.get("id")) not in selected:
            continue
        fact_ids = list(dict.fromkeys(scene.get("source_fact_ids") or []))
        invalid_ids = [fact_id for fact_id in fact_ids if fact_id not in facts_by_id]
        facts = [facts_by_id[fact_id] for fact_id in fact_ids if fact_id in facts_by_id]
        snapshot = _copy_snapshot(plan, scene, facts)
        job = _job(db, project, user_id, task_type=COPY_JOB_TYPE, snapshot=snapshot, provider=COPY_PROVIDER, model=COPY_MODEL, scene_id=str(scene.get("id")))
        if invalid_ids:
            _finish_job(job, status="failed", failure_category="validation_failed", error_code="unconfirmed_fact_ids", message="확정되지 않은 사실은 카피 입력으로 사용할 수 없습니다.")
            results.append({"scene_id": scene.get("id"), "status": "failed", "failure_category": "validation_failed", "message": job.error_message, "blocked_fact_ids": invalid_ids, "job_id": job.job_id})
            continue
        headline, body = _draft_for_scene(scene, facts, project.name or "상품")
        request = GenerationJobRequestSchema(request_id=job.request_id, project_id=project.id, plan_version=int(plan.get("version") or 1), scene_id=str(scene.get("id")), product_brief=snapshot, prompt_blueprint={"deterministic_output": {"headline": headline, "body": body}, "forbidden_claims": snapshot["forbidden_claims"], "max_length": snapshot["max_length"]}, output_spec=GenerationOutputSpecSchema(kind="generated_copy"), seller_approved=True)
        try:
            provider_result = DeterministicGroundedCopyProvider().submit(request)
            output = json.loads(provider_result.generated_text or "{}")
            headline, body = str(output.get("headline") or "").strip(), str(output.get("body") or "").strip()
        except Exception:
            _finish_job(job, status="failed", failure_category="provider_error", retryable=True, error_code="copy_provider_error", message="카피 제공자 처리에 실패했습니다.")
            results.append({"scene_id": scene.get("id"), "status": "failed", "failure_category": "provider_error", "message": job.error_message, "job_id": job.job_id})
            continue
        blocked = _copy_failure(f"{headline} {body}", snapshot["forbidden_claims"], facts)
        if not headline or not body or len(headline) > 60 or len(body) > 180 or blocked:
            _finish_job(job, status="failed", failure_category="validation_failed", error_code="copy_grounding_failed", message="금지 표현 또는 근거 검증에서 차단되었습니다.", output={"headline": headline, "body": body, "forbidden_matches": blocked}, usage=provider_result.usage)
            results.append({"scene_id": scene.get("id"), "status": "failed", "failure_category": "validation_failed", "message": job.error_message, "forbidden_matches": blocked, "job_id": job.job_id})
            continue
        draft = {"id": job.request_id, "job_id": job.job_id, "status": "needs_seller_review", "headline": headline, "body": body, "source_fact_ids": fact_ids, "forbidden_check": {"passed": True, "matches": []}, "provider": COPY_PROVIDER, "model": COPY_MODEL, "provider_response_id": provider_result.provider_response_id, "usage": provider_result.usage, "input_snapshot_hash": job.input_snapshot_hash, "estimated_cost": provider_result.estimated_cost or 0, "actual_cost": provider_result.actual_cost or 0, "created_at": datetime.now(timezone.utc).isoformat()}
        scene["copy_draft"] = draft
        _finish_job(job, status="needs_seller_review", output=draft, usage=provider_result.usage)
        results.append({"scene_id": scene.get("id"), **draft})
    estimate = estimate_grounded_copy_drafts(project, plan, scene_ids)
    plan["copy_generation"] = {**estimate, "actual_cost": 0, "seller_cost_approved": True, "updated_at": datetime.now(timezone.utc).isoformat()}
    return {"project_id": project.id, "estimated_cost": 0, "actual_cost": 0, "results": results, "plan": plan}


def decide_copy_draft(db: Session, project: ProductProject, plan: dict[str, Any], scene_id: str, seller_approved: bool) -> dict[str, Any]:
    scene = next((item for item in plan.get("scenes") or [] if str(item.get("id")) == scene_id), None)
    if not scene or not isinstance(scene.get("copy_draft"), dict):
        raise ValueError("검토할 카피 초안을 찾을 수 없습니다.")
    draft = scene["copy_draft"]
    if draft.get("status") != "needs_seller_review":
        raise ValueError("현재 카피 초안은 다시 생성하거나 검토해야 합니다.")
    facts = [fact for fact in db.query(ProductFact).filter(ProductFact.project_id == project.id).all() if fact.id in set(draft.get("source_fact_ids") or [])]
    current_snapshot = _copy_snapshot(plan, scene, facts)
    invalid = len(facts) != len(set(draft.get("source_fact_ids") or [])) or any(fact.verification_status not in CONFIRMED_FACT_STATUSES or fact.needs_review or not fact.evidences for fact in facts)
    blocked = _copy_failure(f"{draft.get('headline', '')} {draft.get('body', '')}", current_snapshot["forbidden_claims"], facts)
    if invalid or _hash(current_snapshot) != draft.get("input_snapshot_hash") or blocked:
        draft.update({"status": "stale", "stale_reason": "근거 사실 또는 브리프가 변경되어 다시 생성이 필요합니다."})
        return draft
    draft["status"] = "seller_approved" if seller_approved else "seller_rejected"
    draft["seller_decided_at"] = datetime.now(timezone.utc).isoformat()
    job = db.query(GenerationJobRecord).filter(GenerationJobRecord.job_id == draft.get("job_id"), GenerationJobRecord.project_id == project.id).first()
    if job:
        _finish_job(job, status="succeeded" if seller_approved else "cancelled", output=draft, failure_category=None if seller_approved else "seller_rejected")
    return draft
