from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import (
    AgentRun,
    AgentRunStep,
    AiJobLog,
    ExportJob,
    ImageGenerationJobRecord,
    ProductProject,
)


ACTIVE_AGENT_STATUSES = {"created", "running"}
ACTIVE_IMAGE_STATUSES = {"planned", "awaiting_cost_approval", "generating", "needs_review"}
ACTIVE_EXPORT_STATUSES = {"pending", "running"}


_SELLER_ERROR_CODES = frozenset({
    "API_KEY_MISSING",
    "BALANCE_OR_LIMIT",
    "EXPORT_FAILED",
    "GRAPH_EXECUTION_FAILED",
    "GRAPH_STEP_FAILED",
    "IDENTITY_MISMATCH",
    "IDENTITY_GATE_REJECTED",
    "IMAGE_DELIVERY_FAILED",
    "IMAGE_GENERATION_FAILED",
    "IMAGE_JOB_DISPATCH_FAILED",
    "IMAGE_JOB_PREPARE_FAILED",
    "IMAGE_PROVIDER_NOT_CONFIGURED",
    "OCR_CONTAMINATION",
    "PRE_DISPATCH_FAILURE",
    "PROVIDER_ERROR",
    "PROVIDER_OUTCOME_UNKNOWN",
    "PROVIDER_SAFETY",
    "PROVIDER_TIMEOUT",
    "QUALITY_GATE_FAILED",
    "RIGHTS_BLOCKED",
    "SAFE_REFERENCE_ASSET_REQUIRED",
    "STALE_DELIVERY_BLOCKED",
    "UNSAFE_GENERATED_CONTENT_DETECTED",
})

_SELLER_GUIDANCE_BY_CODE = {
    "API_KEY_MISSING": ("이미지 생성 설정을 확인해야 합니다.", "설정을 확인한 뒤 같은 작업을 다시 시도하세요.", "retry", True),
    "BALANCE_OR_LIMIT": ("이미지 생성 사용 한도를 확인해야 합니다.", "사용 한도를 확인한 뒤 실패한 장면을 다시 생성하세요.", "retry", True),
    "PROVIDER_TIMEOUT": ("이미지 생성 응답이 늦어 완료하지 못했습니다.", "잠시 후 실패한 장면을 다시 생성하세요.", "retry", True),
    "PROVIDER_SAFETY": ("이미지 요청이 안전 기준으로 처리되지 않았습니다.", "상품 사진 또는 요청 내용을 확인한 뒤 다시 생성하세요.", "regenerate", True),
    "IDENTITY_MISMATCH": ("생성 이미지가 상품 사진과 충분히 일치하지 않습니다.", "상품 사진을 확인한 뒤 장면을 다시 생성하세요.", "regenerate", True),
    "IDENTITY_GATE_REJECTED": ("생성 이미지가 상품 사진과 충분히 일치하지 않습니다.", "상품 사진을 확인한 뒤 장면을 다시 생성하세요.", "regenerate", True),
    "OCR_CONTAMINATION": ("생성 이미지에서 확인이 필요한 문구가 감지되었습니다.", "이미지를 검토하고 필요하면 장면을 다시 생성하세요.", "review", True),
    "RIGHTS_BLOCKED": ("사용 권한을 확인할 수 없는 이미지가 포함되었습니다.", "권리 보유 상품 사진을 선택한 뒤 다시 생성하세요.", "upload_reference", True),
    "SAFE_REFERENCE_ASSET_REQUIRED": ("생성에 사용할 수 있는 상품 사진이 필요합니다.", "권리 보유 상품 사진을 추가한 뒤 다시 시도하세요.", "upload_reference", True),
    "PROVIDER_OUTCOME_UNKNOWN": ("이미지 생성 결과를 아직 확인하지 못했습니다.", "작업 상태를 새로고침한 뒤 필요하면 장면을 다시 생성하세요.", "refresh_status", False),
    "STALE_DELIVERY_BLOCKED": ("이전 이미지 작업 결과는 적용하지 않았습니다.", "최신 작업 상태를 확인하세요.", "refresh_status", False),
    "UNSAFE_GENERATED_CONTENT_DETECTED": ("생성 이미지에서 확인이 필요한 요소가 감지되었습니다.", "이미지를 검토하고 필요하면 장면을 다시 생성하세요.", "review", True),
    "IMAGE_PROVIDER_NOT_CONFIGURED": ("이미지 생성을 시작할 준비가 되지 않았습니다.", "설정을 확인한 뒤 다시 시도하세요.", "retry", True),
    "IMAGE_JOB_PREPARE_FAILED": ("이미지 생성 작업을 준비하지 못했습니다.", "잠시 후 같은 작업을 다시 시도하세요.", "retry", True),
    "IMAGE_JOB_DISPATCH_FAILED": ("이미지 생성 요청을 시작하지 못했습니다.", "잠시 후 같은 작업을 다시 시도하세요.", "retry", True),
}

_SELLER_GUIDANCE_BY_REVIEW_STAGE = {
    "input_review": ("입력 내용을 확인해야 합니다.", "내용을 확인한 뒤 승인하거나 수정 요청하세요.", "review"),
    "evidence_review": ("상품 근거를 확인해야 합니다.", "확인한 뒤 승인하거나 수정 요청하세요.", "review"),
    "planning_review": ("구성 계획을 확인해야 합니다.", "내용을 확인한 뒤 승인하거나 수정 요청하세요.", "review"),
    "generation_pending": ("이미지 생성 전에 비용 확인이 필요합니다.", "예상 비용을 확인한 뒤 생성을 승인하세요.", "approve_cost"),
    "provider_wait": ("이미지 생성 결과를 확인하고 있습니다.", "잠시 후 작업 상태를 새로고침하세요.", "refresh_status"),
    "image_review": ("생성 이미지를 확인해야 합니다.", "장면별로 승인, 거절 또는 다시 생성을 선택하세요.", "review"),
    "edit_confirmation": ("수정 내용을 확인해야 합니다.", "내용을 확인한 뒤 승인하거나 수정 요청하세요.", "review"),
    "canvas_edit": ("페이지 구성을 확인해야 합니다.", "변경 내용을 확인한 뒤 저장하세요.", "review"),
    "seller_confirmation": ("상품 정보를 확인해야 합니다.", "확인 항목을 입력한 뒤 계속 진행하세요.", "confirm_details"),
    "quality_review": ("최종 결과를 확인해야 합니다.", "결과를 승인하거나 수정 요청하세요.", "review"),
}

_SELLER_GUIDANCE_BY_DELAY_CAUSE = {
    "queue_wait": ("생성 작업을 준비하고 있습니다.", "잠시 기다리면 자동으로 계속 진행됩니다.", "refresh_status", False, False),
    "provider_execution": ("이미지를 생성하고 있습니다.", "완료되면 다음 단계가 자동으로 진행됩니다.", "refresh_status", False, False),
    "retry_backoff": ("일시적인 문제로 다시 시도할 준비를 하고 있습니다.", "자동 재시도가 예정되어 있습니다.", "refresh_status", True, False),
    "recovery_reconciled": ("작업 상태를 안전하게 다시 확인하고 있습니다.", "잠시 후 상태를 다시 확인하세요.", "refresh_status", False, False),
    "graph_compute": ("생성 내용을 준비하고 있습니다.", "잠시 후 작업 상태를 다시 확인하세요.", "refresh_status", False, False),
    "rendering_quality": ("결과 품질을 확인하고 있습니다.", "잠시 후 작업 상태를 다시 확인하세요.", "refresh_status", False, False),
    "seller_review_wait": ("확인이 필요한 항목이 있습니다.", "내용을 확인한 뒤 선택해 주세요.", "review", False, True),
    "unknown": ("작업 상태를 확인하고 있습니다.", "잠시 후 작업 상태를 다시 확인하세요.", "refresh_status", False, False),
}


def bounded_error_code(value: object, fallback: str = "GRAPH_EXECUTION_FAILED") -> str:
    """Keep diagnostic or provider text out of public projection contracts."""

    candidate = str(value or "")
    return candidate if candidate in _SELLER_ERROR_CODES else fallback


def seller_guidance(
    state: object,
    *,
    code: object = None,
    review_stage: object = None,
    retryable: bool | None = None,
    delay_cause: object = None,
) -> dict[str, Any]:
    """Derive the one bounded Korean seller cause/action view from safe state."""

    status = str(state or "unknown")
    stage = str(review_stage or "")
    safe_code = bounded_error_code(code) if code else None
    delay = str(delay_cause or "")
    if delay in _SELLER_GUIDANCE_BY_DELAY_CAUSE:
        cause, action, action_type, delay_retryable, review_required = _SELLER_GUIDANCE_BY_DELAY_CAUSE[delay]
        return {
            "status": "awaiting_review" if review_required else "running",
            "safe_code": safe_code,
            "cause_ko": cause,
            "action_ko": action,
            "action_type": action_type,
            "retryable": delay_retryable if retryable is None else bool(retryable),
            "review_required": review_required,
        }
    if stage in _SELLER_GUIDANCE_BY_REVIEW_STAGE:
        cause, action, action_type = _SELLER_GUIDANCE_BY_REVIEW_STAGE[stage]
        return {
            "status": "awaiting_review",
            "safe_code": safe_code,
            "cause_ko": cause,
            "action_ko": action,
            "action_type": action_type,
            "retryable": False,
            "review_required": True,
        }
    if safe_code:
        cause, action, action_type, default_retryable = _SELLER_GUIDANCE_BY_CODE.get(
            safe_code,
            ("작업을 완료하지 못했습니다.", "원인을 확인한 뒤 같은 작업을 다시 시도하세요.", "retry", True),
        )
        return {
            "status": "failed",
            "safe_code": safe_code,
            "cause_ko": cause,
            "action_ko": action,
            "action_type": action_type,
            "retryable": default_retryable if retryable is None else bool(retryable),
            "review_required": action_type == "review",
        }
    cause, action, action_type = {
        "completed": ("작업이 완료되었습니다.", "결과를 확인하세요.", "view_result"),
        "waiting_for_cost_approval": ("이미지 생성 전에 비용 확인이 필요합니다.", "예상 비용을 확인한 뒤 생성을 승인하세요.", "approve_cost"),
        "needs_review": ("확인이 필요한 결과가 있습니다.", "결과를 확인한 뒤 다음 단계를 선택하세요.", "review"),
        "failed": ("작업을 완료하지 못했습니다.", "원인을 확인한 뒤 같은 작업을 다시 시도하세요.", "retry"),
        "created": ("작업을 시작할 준비가 되었습니다.", "작업을 계속 진행하세요.", "continue"),
        "running": ("작업을 진행하고 있습니다.", "잠시 후 상태를 다시 확인하세요.", "refresh_status"),
        "not_started": ("아직 작업을 시작하지 않았습니다.", "새 작업을 시작하세요.", "start"),
    }.get(status, ("작업 상태를 확인하고 있습니다.", "잠시 후 상태를 다시 확인하세요.", "refresh_status"))
    return {
        "status": status if status in {"completed", "waiting_for_cost_approval", "needs_review", "failed", "created", "running", "not_started"} else "unknown",
        "safe_code": None,
        "cause_ko": cause,
        "action_ko": action,
        "action_type": action_type,
        "retryable": False,
        "review_required": status == "needs_review",
    }

def _public_error_code(value: object, fallback: str) -> str:
    """Never make persisted diagnostic text part of a seller status response."""

    return bounded_error_code(value, fallback)


class GenerationStatusService:
    def __init__(self, db: Session):
        self.db = db

    def get_workspace_status(self, workspace_id: str) -> dict[str, Any]:
        projects = (
            self.db.query(ProductProject)
            .filter(ProductProject.workspace_id == workspace_id)
            .order_by(ProductProject.updated_at.desc())
            .all()
        )
        project_statuses = [
            self._compact_project_status(self.get_project_status(project.id, workspace_id))
            for project in projects
        ]
        state_counts = Counter(item["state"] for item in project_statuses)
        return {
            "summary": {
                "running": state_counts.get("running", 0),
                "waiting_for_cost_approval": state_counts.get("waiting_for_cost_approval", 0),
                "needs_review": state_counts.get("needs_review", 0),
                "completed": state_counts.get("completed", 0),
                "failed": state_counts.get("failed", 0),
                "estimated_cost": round(sum(item["cost"]["estimated"] or 0 for item in project_statuses), 4),
                "actual_cost": round(sum(item["cost"]["actual"] or 0 for item in project_statuses), 4),
                "has_unknown_cost": any(bool(item["cost"].get("has_unknown_cost")) for item in project_statuses),
                "provider_attempt_count": sum(int(item["cost"].get("provider_attempt_count") or 0) for item in project_statuses),
            },
            "projects": project_statuses,
        }

    def get_project_status(self, project_id: str, workspace_id: str) -> dict[str, Any]:
        project = (
            self.db.query(ProductProject)
            .filter(ProductProject.id == project_id, ProductProject.workspace_id == workspace_id)
            .first()
        )
        if project is None:
            raise ValueError(f"ProductProject not found: {project_id}")

        latest_run = self._latest_run(project_id, workspace_id)
        steps = self._steps(latest_run.id) if latest_run else []
        image_jobs = self._image_jobs(project_id)
        export_jobs = self._export_jobs(project_id)
        ai_logs = self._ai_logs(project_id)

        state = self._derive_state(project, latest_run, image_jobs, export_jobs)
        current_stage = self._derive_current_stage(project, latest_run, export_jobs)
        failed_step = next((step for step in steps if step.status == "failed"), None)
        last_error = self._derive_error(latest_run, failed_step, export_jobs, image_jobs)
        delay_context = None
        progress_preview = None
        seller_choice = None
        if latest_run:
            from src.services.langgraph_run_service import AgentRunEventJournal, seller_progressive_preview, seller_slo08_choice

            delay_context = AgentRunEventJournal.seller_delay_context(latest_run, self.db)
            progress_preview = seller_progressive_preview(latest_run, self.db)
            seller_choice = seller_slo08_choice(latest_run)

        estimated_cost = latest_run.estimated_cost if latest_run and latest_run.estimated_cost is not None else 0.0
        actual_cost = latest_run.actual_cost if latest_run and latest_run.actual_cost is not None else 0.0
        cost_projection = dict((latest_run.outputs_json or {}).get("provider_cost_projection") or {}) if latest_run else {}
        token_input = 0
        token_output = 0
        for step in steps:
            usage = step.token_usage or {}
            token_input += int(usage.get("input_tokens") or 0)
            token_output += int(usage.get("output_tokens") or 0)
        for log in ai_logs:
            token_input += int(log.input_tokens or 0)
            token_output += int(log.output_tokens or 0)

        return {
            "project_id": project.id,
            "project_name": project.name,
            "state": state,
            "current_stage": current_stage,
            "failed_stage": failed_step.stage if failed_step else None,
            "progress_percent": self._progress_percent(state, progress_preview),
            "can_start_new_run": state not in {"created", "running", "waiting_for_cost_approval", "needs_review"},
            "recommended_action": self._recommended_action(state),
            "seller_guidance": seller_guidance(
                state,
                code=last_error,
                retryable=True if state == "failed" and not last_error else None,
            ),
            "delay_context": delay_context,
            "progress_preview": progress_preview,
            "seller_choice": seller_choice,
            "result_url": f"/workspace/projects/{project.id}/result" if state == "completed" else None,
            "review_url": f"/workspace/projects/{project.id}/page-editor?mode=review" if state in {"needs_review", "completed"} else None,
            "active_run": self._serialize_run(latest_run),
            "steps": [self._serialize_step(step) for step in steps],
            "image_jobs": self._summarize_image_jobs(image_jobs),
            "export_jobs": self._summarize_export_jobs(export_jobs),
            "cost": {
                "estimated": round(estimated_cost, 4),
                "actual": round(actual_cost, 4),
                "actual_cost_complete": bool(cost_projection.get("actual_cost_complete", True)),
                "has_unknown_cost": bool(cost_projection.get("has_unknown_cost", False)),
                "provider_attempt_count": int(cost_projection.get("attempt_count") or 0),
                "token_input": token_input,
                "token_output": token_output,
            },
            "last_error": last_error,
            "updated_at": (latest_run.updated_at if latest_run else project.updated_at).isoformat(),
        }

    def _latest_run(self, project_id: str, workspace_id: str) -> AgentRun | None:
        return (
            self.db.query(AgentRun)
            .filter(AgentRun.project_id == project_id, AgentRun.workspace_id == workspace_id)
            .order_by(AgentRun.created_at.desc())
            .first()
        )

    def _steps(self, run_id: str) -> list[AgentRunStep]:
        return (
            self.db.query(AgentRunStep)
            .filter(AgentRunStep.run_id == run_id)
            .order_by(AgentRunStep.started_at.asc().nullslast(), AgentRunStep.stage.asc())
            .all()
        )

    def _image_jobs(self, project_id: str) -> list[ImageGenerationJobRecord]:
        return (
            self.db.query(ImageGenerationJobRecord)
            .filter(ImageGenerationJobRecord.project_id == project_id)
            .order_by(ImageGenerationJobRecord.updated_at.desc())
            .all()
        )

    def _export_jobs(self, project_id: str) -> list[ExportJob]:
        return (
            self.db.query(ExportJob)
            .filter(ExportJob.project_id == project_id)
            .order_by(ExportJob.created_at.desc())
            .all()
        )

    def _ai_logs(self, project_id: str) -> list[AiJobLog]:
        return self.db.query(AiJobLog).filter(AiJobLog.project_id == project_id).all()

    def _derive_state(
        self,
        project: ProductProject,
        latest_run: AgentRun | None,
        image_jobs: list[ImageGenerationJobRecord],
        export_jobs: list[ExportJob],
    ) -> str:
        if latest_run and latest_run.status == "failed":
            return "failed"
        if latest_run and latest_run.status in ACTIVE_AGENT_STATUSES:
            return latest_run.status
        if any(job.status in ACTIVE_EXPORT_STATUSES for job in export_jobs):
            return "running"
        if any(job.status == "awaiting_cost_approval" for job in image_jobs):
            return "waiting_for_cost_approval"
        if any(job.status in {"needs_review", "rejected", "failed"} for job in image_jobs):
            return "needs_review"
        if latest_run and latest_run.status == "completed":
            return "completed"
        if project.status in {"completed", "ready"}:
            return "completed"
        return "not_started"

    def _derive_current_stage(
        self,
        project: ProductProject,
        latest_run: AgentRun | None,
        export_jobs: list[ExportJob],
    ) -> str:
        if any(job.status in ACTIVE_EXPORT_STATUSES for job in export_jobs):
            return "export"
        if latest_run:
            return latest_run.current_stage
        return project.current_step or "not_started"

    def _derive_error(
        self,
        latest_run: AgentRun | None,
        failed_step: AgentRunStep | None,
        export_jobs: list[ExportJob],
        image_jobs: list[ImageGenerationJobRecord],
    ) -> str | None:
        if failed_step and failed_step.error_message:
            return _public_error_code(failed_step.error_message, "GRAPH_STEP_FAILED")
        if latest_run and latest_run.error_log:
            last = latest_run.error_log[-1]
            if isinstance(last, dict):
                return _public_error_code(last.get("code"), "GRAPH_EXECUTION_FAILED")
        failed_export = next((job for job in export_jobs if job.status == "failed" and job.error_message), None)
        if failed_export:
            return "EXPORT_FAILED"
        failed_image = next((job for job in image_jobs if job.status == "failed" and job.error_code), None)
        if failed_image:
            return _public_error_code(failed_image.error_code, "IMAGE_GENERATION_FAILED")
        return None

    def _progress_percent(self, state: str, progress_preview: dict[str, Any] | None) -> int:
        if state == "completed":
            return 100
        if progress_preview is not None:
            return int(progress_preview.get("progress_percent") or 0)
        return 0

    def _recommended_action(self, state: str) -> str:
        return {
            "not_started": "start_new_run",
            "created": "continue_run",
            "running": "view_status",
            "waiting_for_cost_approval": "approve_cost_or_continue_mock",
            "needs_review": "open_review",
            "completed": "view_result",
            "failed": "retry_failed_stage",
        }.get(state, "view_status")

    def _summarize_image_jobs(self, jobs: list[ImageGenerationJobRecord]) -> dict[str, int]:
        counts = Counter(job.status for job in jobs)
        return {
            "total": len(jobs),
            "planned": counts.get("planned", 0),
            "awaiting_cost_approval": counts.get("awaiting_cost_approval", 0),
            "generating": counts.get("generating", 0),
            "needs_review": counts.get("needs_review", 0),
            "approved": counts.get("approved", 0),
            "failed": counts.get("failed", 0),
        }

    def _summarize_export_jobs(self, jobs: list[ExportJob]) -> dict[str, Any]:
        latest = jobs[0] if jobs else None
        return {
            "total": len(jobs),
            "latest_status": latest.status if latest else "none",
        }

    def _serialize_run(self, run: AgentRun | None) -> dict[str, Any] | None:
        if run is None:
            return None
        return {
            "id": run.id,
            "status": run.status,
            "current_stage": run.current_stage,
            "estimated_cost": run.estimated_cost,
            "actual_cost": run.actual_cost,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        }

    def _serialize_step(self, step: AgentRunStep) -> dict[str, Any]:
        usage = step.token_usage or {}
        return {
            "stage": step.stage,
            "status": step.status,
            "estimated_cost": step.estimated_cost,
            "actual_cost": None,
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "error_message": _public_error_code(step.error_message, "GRAPH_STEP_FAILED") if step.error_message else None,
        }

    def _compact_project_status(self, status: dict[str, Any]) -> dict[str, Any]:
        return {
            "project_id": status["project_id"],
            "project_name": status["project_name"],
            "state": status["state"],
            "current_stage": status["current_stage"],
            "progress_percent": status["progress_percent"],
            "can_start_new_run": status["can_start_new_run"],
            "recommended_action": status["recommended_action"],
            "seller_guidance": status["seller_guidance"],
            "delay_context": status["delay_context"],
            "progress_preview": status["progress_preview"],
            "seller_choice": status["seller_choice"],
            "cost": status["cost"],
            "updated_at": status["updated_at"],
        }
