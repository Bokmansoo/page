"""LG-4 seller-review interrupt contracts.

The payload held by LangGraph must be small, versioned, and safe to restore
after a browser refresh.  This module deliberately contains no ORM/session
objects and never includes provider credentials, source text, or image bytes.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


LG4_REVIEW_SCHEMA_VERSION = "lg4-v1"
LG5_REVIEW_SCHEMA_VERSION = "lg5-v1"
ReviewStage = Literal[
    "input_review", "evidence_review", "planning_review", "generation_pending", "provider_wait", "image_review",
]
ReviewDecision = Literal["approve", "reject", "defer", "refresh", "regenerate", "upload"]


class GraphReviewResumePayload(BaseModel):
    """The only value that may resume an LG-4 interrupt."""

    schema_version: Literal["lg4-v1", "lg5-v1"] = LG4_REVIEW_SCHEMA_VERSION
    review_stage: ReviewStage
    decision: ReviewDecision
    comment: str = Field(default="", max_length=1000)
    job_id: str = Field(default="", max_length=100)
    asset_id: str = Field(default="", max_length=100)
    seller_attested: bool = False
    cost_plan_hash: str = Field(default="", max_length=64)

    @field_validator("comment")
    @classmethod
    def _strip_comment(cls, value: str) -> str:
        return value.strip()


def review_interrupt_payload(
    stage: ReviewStage,
    state: dict[str, Any],
    *,
    rejection_reason: str = "",
    schema_version: str | None = None,
) -> dict[str, Any]:
    """Return the persisted, browser-safe request displayed to a seller."""

    content = {
        "input_review": {
            "title": "상품 입력 확인",
            "description": "입력한 상품명·사진·판매자 정보를 확인한 뒤 다음 분석을 시작합니다.",
            "allowed_decisions": ["approve", "reject"],
        },
        "evidence_review": {
            "title": "근거 사실 확인",
            "description": "확정 사실과 자료 수집 결과를 확인한 뒤 판매 전략을 만듭니다.",
            "allowed_decisions": ["approve", "reject"],
        },
        "planning_review": {
            "title": "스토리보드 승인",
            "description": "섹션·카피·장면 계획을 확인한 뒤 이미지 생성 대기 단계로 보냅니다.",
            "allowed_decisions": ["approve", "reject"],
        },
        "generation_pending": {
            "title": "이미지 생성 비용·제공자 확인",
            "description": "예상 비용과 장면 수를 확인한 뒤 승인하면 같은 실행에서 이미지 작업을 시작합니다.",
            "allowed_decisions": ["approve", "defer"],
        },
        "provider_wait": {
            "title": "이미지 생성 작업 진행 중",
            "description": "제공자 작업 결과를 수집하고 있습니다. 완료되면 같은 실행이 이미지 검수 단계로 자동 이동합니다.",
            "allowed_decisions": ["refresh"],
        },
        "image_review": {
            "title": "생성 이미지 검수",
            "description": "생성 결과를 기준 사진과 비교한 뒤 승인·재생성·직접 업로드를 선택해 주세요.",
            "allowed_decisions": ["approve", "reject", "regenerate", "upload"],
        },
    }[stage]
    snapshot = state.get("input_snapshot") or {}
    discovery = state.get("discovery") or {}
    commerce = state.get("commerce") or {}
    return {
        "schema_version": schema_version or (LG5_REVIEW_SCHEMA_VERSION if stage in {"generation_pending", "provider_wait", "image_review"} else LG4_REVIEW_SCHEMA_VERSION),
        "review_stage": stage,
        **content,
        "run_id": str(state.get("run_id") or ""),
        "thread_id": str(state.get("thread_id") or state.get("run_id") or ""),
        "project_id": str(state.get("project_id") or ""),
        "context": {
            "product_name": str(snapshot.get("product_name") or ""),
            "approved_fact_snapshot_id": str(snapshot.get("approved_fact_snapshot_id") or ""),
            "discovery_stages": sorted(str(key) for key in discovery),
            "planning_stages": sorted(str(key) for key in commerce),
            "generation": dict(state.get("generation") or {}),
        },
        "rejection_reason": rejection_reason,
    }


def validate_resume_payload(value: Any, expected_stage: str) -> GraphReviewResumePayload:
    """Validate a resume command against the currently interrupted stage."""

    payload = GraphReviewResumePayload.model_validate(value)
    if payload.review_stage != expected_stage:
        raise ValueError("Resume payload review_stage does not match the pending graph interrupt.")
    allowed = {
        "generation_pending": {"approve", "defer"},
        "provider_wait": {"refresh"},
        "image_review": {"approve", "reject", "regenerate", "upload"},
    }.get(expected_stage, {"approve", "reject"})
    if payload.decision not in allowed:
        raise ValueError(f"{expected_stage} does not accept the '{payload.decision}' decision.")
    if expected_stage == "image_review" and payload.decision == "upload" and not payload.asset_id:
        raise ValueError("image_review upload requires an asset_id.")
    return payload


def validate_resume_against_interrupt(value: Any, pending: dict[str, Any]) -> GraphReviewResumePayload:
    """Reject stale UI responses before invoking ``Command(resume=...)``."""

    stage = str(pending.get("review_stage") or "")
    payload = validate_resume_payload(value, stage)
    if payload.schema_version != pending.get("schema_version"):
        raise ValueError("승인 화면 버전이 변경되었습니다. 상태를 새로고침한 뒤 다시 시도해 주세요.")
    generation = dict((pending.get("context") or {}).get("generation") or {})
    if stage == "generation_pending" and pending.get("schema_version") == LG5_REVIEW_SCHEMA_VERSION:
        expected_hash = str((generation.get("cost_plan") or {}).get("cost_plan_hash") or "")
        if not payload.cost_plan_hash or payload.cost_plan_hash != expected_hash:
            raise ValueError("비용 계획이 변경되었습니다. 최신 장면별 비용을 다시 확인해 주세요.")
    if stage == "image_review":
        jobs = {str(job.get("job_id") or "") for job in generation.get("jobs") or []}
        if payload.decision in {"approve", "reject", "upload"} and payload.job_id not in jobs:
            raise ValueError("검수할 장면이 변경되었습니다. 상태를 새로고침하고 장면을 다시 선택해 주세요.")
        if payload.decision == "regenerate" and payload.job_id and payload.job_id not in jobs:
            raise ValueError("재생성할 장면이 변경되었습니다. 상태를 새로고침해 주세요.")
    return payload


def approval_blocker(stage: str, state: dict[str, Any]) -> str:
    """Return a seller-facing blocker before an approval advances the graph.

    Visual planning cannot safely proceed without at least one seller-owned,
    provider-safe image. Checking this at ``evidence_review`` keeps the graph
    at a recoverable interrupt instead of turning a correct approval click
    into a failed run several nodes later.
    """

    if stage != "evidence_review":
        return ""

    from src.db.database import SessionLocal
    from src.db.models import Asset
    from src.services.api_ready_generation_service import is_safe_generation_reference
    from src.services.langgraph_discovery_service import current_langgraph_session

    db = current_langgraph_session()
    owns_session = db is None
    if db is None:
        db = SessionLocal()
    try:
        project_id = str(state.get("project_id") or "")
        assets = db.query(Asset).filter(Asset.project_id == project_id).all()
        if any(is_safe_generation_reference(asset, db) for asset in assets):
            return ""
        return (
            "AI 비주얼 기획에 사용할 안전한 권리 보유 사진이 없습니다. "
            "글자·로고가 노출되지 않은 제품 사진을 ‘권리 보유 이미지’ 또는 "
            "‘직접 촬영 사진’으로 추가한 뒤 다시 확인해 주세요."
        )
    finally:
        if owns_session:
            db.close()
