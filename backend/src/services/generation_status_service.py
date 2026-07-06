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

STAGE_PROGRESS = {
    "intake": 5,
    "input_router": 10,
    "source_collection": 18,
    "product_understanding": 26,
    "reference_analysis": 34,
    "sales_strategy": 42,
    "page_planning": 50,
    "copywriting": 58,
    "visual_planning": 66,
    "image_generation": 76,
    "page_assembly": 86,
    "qa_review": 94,
    "review_editor": 100,
    "export": 100,
}


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

        estimated_cost = latest_run.estimated_cost if latest_run and latest_run.estimated_cost is not None else 0.0
        actual_cost = latest_run.actual_cost if latest_run and latest_run.actual_cost is not None else 0.0
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
            "progress_percent": self._progress_percent(state, current_stage),
            "can_start_new_run": state not in {"created", "running", "waiting_for_cost_approval", "needs_review"},
            "recommended_action": self._recommended_action(state),
            "result_url": f"/workspace/projects/{project.id}/result" if state == "completed" else None,
            "review_url": f"/workspace/projects/{project.id}/page-editor?mode=review" if state in {"needs_review", "completed"} else None,
            "active_run": self._serialize_run(latest_run),
            "steps": [self._serialize_step(step) for step in steps],
            "image_jobs": self._summarize_image_jobs(image_jobs),
            "export_jobs": self._summarize_export_jobs(export_jobs),
            "cost": {
                "estimated": round(estimated_cost, 4),
                "actual": round(actual_cost, 4),
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
            return failed_step.error_message
        if latest_run and latest_run.error_log:
            last = latest_run.error_log[-1]
            if isinstance(last, dict):
                return str(last.get("message") or "")
        failed_export = next((job for job in export_jobs if job.status == "failed" and job.error_message), None)
        if failed_export:
            return failed_export.error_message
        failed_image = next((job for job in image_jobs if job.status == "failed" and job.error_code), None)
        if failed_image:
            return failed_image.error_code
        return None

    def _progress_percent(self, state: str, current_stage: str) -> int:
        if state == "completed":
            return 100
        if state == "failed":
            return STAGE_PROGRESS.get(current_stage, 0)
        return STAGE_PROGRESS.get(current_stage, 0)

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
            "error_message": step.error_message,
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
            "cost": status["cost"],
            "updated_at": status["updated_at"],
        }
