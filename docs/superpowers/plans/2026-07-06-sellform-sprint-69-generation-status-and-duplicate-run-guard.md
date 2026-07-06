# Sprint 69 작업 상태 대시보드와 중복 생성 방지 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 상세페이지 생성/이미지 생성/export 작업 상태를 한곳에서 확인하고, 같은 프로젝트를 반복 생성해 토큰과 이미지 비용이 낭비되는 상황을 막는다.

**Architecture:** 기존 `AgentRun`, `AgentRunStep`, `ImageGenerationJobRecord`, `AiJobLog`, `ExportJob`를 새 테이블 없이 통합 조회한다. 백엔드는 프로젝트별 생성 상태 API와 중복 실행 guard를 제공하고, 프론트엔드는 `/workspace/operations`를 “운영 리포트 + 현재 작업 상태” 화면으로 확장한다. 생성 버튼은 실행 전 상태를 확인해 running/completed/failed 상태에 맞는 선택지를 보여준다.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, Next.js App Router, React, Playwright E2E, pytest

---

## 1. 해결하려는 문제

현재 사용자는 상세페이지 생성이 진행 중인지, 실패했는지, 완료됐는지 명확히 보기 어렵다. 그래서 같은 입력으로 생성 버튼을 다시 누르거나, 이미 결과가 있는데 새 프로젝트를 다시 만들 수 있다.

그 결과:

- 텍스트 LLM 토큰이 중복 사용된다.
- 이미지 생성 비용이 중복 발생할 수 있다.
- 같은 상품 프로젝트가 여러 개 생겨 작업 흐름이 헷갈린다.
- 실패 원인이 보이지 않아 “처음부터 다시 생성”으로만 복구하게 된다.

Sprint 69의 핵심은 “생성 전 상태 확인”과 “작업 상태 가시화”다.

---

## 2. 구현 범위

### 포함

- 프로젝트별 통합 작업 상태 API 추가
- workspace 전체 작업 상태 요약 API 추가
- running 작업이 있는 프로젝트의 중복 실행 차단
- `/workspace/operations`에 작업 상태 카드/테이블 추가
- 생성 화면에서 “이미 진행 중/완료/실패” 안내 모달 표시
- 실패 단계만 재시도할 수 있도록 API 계약 정의

### 제외

- 새 background queue 시스템 도입
- 실시간 WebSocket
- 실제 결제/과금 차단 로직
- 이미지 provider별 세부 비용 정산

이번 스프린트는 polling 가능한 상태 API와 UI guard까지 구현한다.

---

## 3. 상태 정의

### Project generation state

| 상태 | 의미 | 사용자 행동 |
|---|---|---|
| `not_started` | 생성 작업 없음 | 새 생성 가능 |
| `created` | 생성 run 생성됨, 아직 실행 전 | 이어서 실행 |
| `running` | agent/image/export 중 하나가 진행 중 | 새 생성 차단, 상태 보기 |
| `waiting_for_cost_approval` | 이미지 생성 비용 승인 대기 | 승인/저비용 모드 선택 |
| `needs_review` | 이미지 정체성 검수 또는 페이지 검수 필요 | 검수 화면으로 이동 |
| `completed` | 상세페이지 결과 있음 | 결과 화면으로 이동, 새 생성은 확인 후 |
| `failed` | 마지막 작업 실패 | 실패 단계 재시도 또는 새로 생성 |

### 중복 실행 기준

같은 프로젝트에 아래 중 하나라도 있으면 새 생성 run을 바로 만들지 않는다.

- `AgentRun.status in ("created", "running")`
- `ImageGenerationJobRecord.status in ("planned", "awaiting_cost_approval", "generating", "needs_review")`
- `ExportJob.status in ("pending", "running")`

완료된 결과가 있으면 새 생성은 가능하지만 확인 모달을 반드시 거친다.

---

## 4. 파일 구조

### Backend

- Create: `backend/src/services/generation_status_service.py`
  - 프로젝트별 agent/image/export 상태를 통합한다.
  - 중복 실행 가능 여부와 추천 action을 계산한다.

- Modify: `backend/src/api/operations.py`
  - `GET /api/v1/operations/generation-status`
  - `GET /api/v1/operations/projects/{project_id}/generation-status`

- Modify: `backend/src/api/agent_runs.py`
  - `POST /api/agent-runs` 생성 전에 중복 실행 guard 적용
  - running/completed/failed 상태별 409 응답 제공

- Create: `backend/tests/test_generation_status_service.py`
  - 상태 계산 단위 테스트

- Create: `backend/tests/test_generation_run_guard.py`
  - 중복 생성 차단 API 테스트

### Frontend

- Create: `frontend/src/lib/generationStatus.ts`
  - status API 타입과 fetch 함수

- Create: `frontend/src/components/GenerationStatusPanel.tsx`
  - operations 화면에서 쓰는 작업 상태 요약/테이블

- Create: `frontend/src/components/GenerationDuplicateRunDialog.tsx`
  - 생성 버튼 누르기 전 running/completed/failed 안내 모달

- Modify: `frontend/src/app/workspace/operations/page.tsx`
  - 기존 운영 리포트 아래에 “현재 생성 작업” 섹션 추가

- Modify: `frontend/src/components/AIDetailPageIntake.tsx`
  - 생성 요청 전 status guard 조회
  - 409 응답을 모달로 표시

- Create: `frontend/e2e/generation-status-guard.spec.ts`
  - running/completed/failed 상태별 UI 검증

---

## 5. API 계약

### `GET /api/v1/operations/projects/{project_id}/generation-status`

응답:

```json
{
  "project_id": "project-1",
  "project_name": "루메나 휴대용 무선 냉각선풍기",
  "state": "running",
  "current_stage": "image_generation",
  "progress_percent": 73,
  "can_start_new_run": false,
  "recommended_action": "view_status",
  "result_url": null,
  "review_url": "/workspace/projects/project-1/page-editor?mode=review",
  "active_run": {
    "id": "run-1",
    "status": "running",
    "current_stage": "image_generation",
    "estimated_cost": 0.12,
    "actual_cost": 0.08,
    "created_at": "2026-07-06T12:00:00",
    "updated_at": "2026-07-06T12:03:00"
  },
  "steps": [
    {
      "stage": "copywriting",
      "status": "completed",
      "estimated_cost": 0.02,
      "actual_cost": 0.018,
      "input_tokens": 1200,
      "output_tokens": 500,
      "error_message": null
    }
  ],
  "image_jobs": {
    "total": 5,
    "pending": 0,
    "generating": 2,
    "needs_review": 1,
    "approved": 2,
    "failed": 0
  },
  "export_jobs": {
    "total": 1,
    "latest_status": "completed"
  },
  "cost": {
    "estimated": 0.12,
    "actual": 0.08,
    "token_input": 1200,
    "token_output": 500
  },
  "last_error": null,
  "updated_at": "2026-07-06T12:03:00"
}
```

### `GET /api/v1/operations/generation-status`

응답:

```json
{
  "summary": {
    "running": 2,
    "waiting_for_cost_approval": 1,
    "needs_review": 3,
    "completed": 8,
    "failed": 1,
    "estimated_cost": 1.42,
    "actual_cost": 1.08
  },
  "projects": [
    {
      "project_id": "project-1",
      "project_name": "루메나 휴대용 무선 냉각선풍기",
      "state": "running",
      "current_stage": "image_generation",
      "progress_percent": 73,
      "can_start_new_run": false,
      "recommended_action": "view_status",
      "cost": {
        "estimated": 0.12,
        "actual": 0.08,
        "token_input": 1200,
        "token_output": 500
      },
      "updated_at": "2026-07-06T12:03:00"
    }
  ]
}
```

### `POST /api/agent-runs` 409 예시

```json
{
  "detail": {
    "code": "generation_already_running",
    "message": "이미 이 상품의 상세페이지 생성이 진행 중입니다.",
    "project_id": "project-1",
    "run_id": "run-1",
    "state": "running",
    "status_url": "/workspace/operations?projectId=project-1",
    "result_url": null
  }
}
```

---

## 6. 작업 계획

### Task 1: GenerationStatusService 단위 테스트 작성

**Files:**

- Create: `backend/tests/test_generation_status_service.py`
- Create: `backend/src/services/generation_status_service.py`

- [ ] **Step 1: 실패하는 service 테스트를 작성한다**

`backend/tests/test_generation_status_service.py`:

```python
import datetime

from src.db.models import (
    AgentRun,
    AgentRunStep,
    ExportJob,
    ImageGenerationJobRecord,
    ProductProject,
)
from src.services.generation_status_service import GenerationStatusService


def test_generation_status_running_when_agent_run_is_running(db_session, test_workspace, test_user, test_brand):
    project = ProductProject(
        workspace_id=test_workspace.id,
        brand_id=test_brand.id,
        name="루메나 휴대용 무선 냉각선풍기",
        status="processing",
        current_step="image_generation",
    )
    db_session.add(project)
    db_session.flush()

    run = AgentRun(
        id="run-running",
        workspace_id=test_workspace.id,
        project_id=project.id,
        mode="real",
        status="running",
        current_stage="image_generation",
        input_snapshot={},
        outputs_json={},
        estimated_cost=0.12,
        actual_cost=0.08,
        created_by=test_user.id,
    )
    db_session.add(run)
    db_session.add(
        AgentRunStep(
            run_id=run.id,
            stage="copywriting",
            status="completed",
            token_usage={"input_tokens": 1200, "output_tokens": 500},
            estimated_cost=0.02,
        )
    )
    db_session.commit()

    status = GenerationStatusService(db_session).get_project_status(project.id, test_workspace.id)

    assert status["state"] == "running"
    assert status["current_stage"] == "image_generation"
    assert status["can_start_new_run"] is False
    assert status["recommended_action"] == "view_status"
    assert status["cost"]["estimated"] == 0.12
    assert status["cost"]["actual"] == 0.08
    assert status["cost"]["token_input"] == 1200
    assert status["cost"]["token_output"] == 500


def test_generation_status_completed_when_project_has_page_and_no_active_jobs(db_session, test_workspace, test_user, test_brand):
    project = ProductProject(
        workspace_id=test_workspace.id,
        brand_id=test_brand.id,
        name="완료된 상세페이지",
        status="completed",
        current_step="review_editor",
    )
    db_session.add(project)
    db_session.flush()

    run = AgentRun(
        id="run-completed",
        workspace_id=test_workspace.id,
        project_id=project.id,
        mode="real",
        status="completed",
        current_stage="review_editor",
        input_snapshot={},
        outputs_json={},
        actual_cost=0.04,
        created_by=test_user.id,
        completed_at=datetime.datetime.utcnow(),
    )
    db_session.add(run)
    db_session.commit()

    status = GenerationStatusService(db_session).get_project_status(project.id, test_workspace.id)

    assert status["state"] == "completed"
    assert status["can_start_new_run"] is True
    assert status["recommended_action"] == "view_result"
    assert status["result_url"] == f"/workspace/projects/{project.id}/result"


def test_generation_status_failed_when_latest_agent_run_failed(db_session, test_workspace, test_user, test_brand):
    project = ProductProject(
        workspace_id=test_workspace.id,
        brand_id=test_brand.id,
        name="실패한 상세페이지",
        status="draft",
        current_step="copywriting",
    )
    db_session.add(project)
    db_session.flush()

    run = AgentRun(
        id="run-failed",
        workspace_id=test_workspace.id,
        project_id=project.id,
        mode="real",
        status="failed",
        current_stage="copywriting",
        input_snapshot={},
        outputs_json={},
        error_log=[{"stage": "copywriting", "message": "LLM provider timeout"}],
        created_by=test_user.id,
    )
    db_session.add(run)
    db_session.add(
        AgentRunStep(
            run_id=run.id,
            stage="copywriting",
            status="failed",
            error_message="LLM provider timeout",
        )
    )
    db_session.commit()

    status = GenerationStatusService(db_session).get_project_status(project.id, test_workspace.id)

    assert status["state"] == "failed"
    assert status["failed_stage"] == "copywriting"
    assert status["last_error"] == "LLM provider timeout"
    assert status["recommended_action"] == "retry_failed_stage"


def test_generation_status_waiting_when_image_cost_approval_is_required(db_session, test_workspace, test_user, test_brand):
    project = ProductProject(
        workspace_id=test_workspace.id,
        brand_id=test_brand.id,
        name="이미지 승인 대기",
        status="processing",
        current_step="image_generation",
    )
    db_session.add(project)
    db_session.flush()

    db_session.add(
        ImageGenerationJobRecord(
            project_id=project.id,
            job_id="image-job-1",
            section_id="hero",
            role="hero",
            prompt="상품 이미지 생성",
            status="awaiting_cost_approval",
        )
    )
    db_session.commit()

    status = GenerationStatusService(db_session).get_project_status(project.id, test_workspace.id)

    assert status["state"] == "waiting_for_cost_approval"
    assert status["can_start_new_run"] is False
    assert status["recommended_action"] == "approve_cost_or_continue_mock"
    assert status["image_jobs"]["total"] == 1
    assert status["image_jobs"]["awaiting_cost_approval"] == 1


def test_generation_status_running_when_export_job_is_running(db_session, test_workspace, test_user, test_brand):
    project = ProductProject(
        workspace_id=test_workspace.id,
        brand_id=test_brand.id,
        name="export 진행 중",
        status="completed",
        current_step="export",
    )
    db_session.add(project)
    db_session.flush()
    db_session.add(
        ExportJob(
            project_id=project.id,
            preset_name="smartstore",
            status="running",
            created_by=test_user.id,
        )
    )
    db_session.commit()

    status = GenerationStatusService(db_session).get_project_status(project.id, test_workspace.id)

    assert status["state"] == "running"
    assert status["current_stage"] == "export"
    assert status["can_start_new_run"] is False
    assert status["export_jobs"]["latest_status"] == "running"
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run:

```bash
uv run --project backend pytest backend/tests/test_generation_status_service.py -q
```

Expected:

```text
FAILED ... ModuleNotFoundError: No module named 'src.services.generation_status_service'
```

---

### Task 2: GenerationStatusService 구현

**Files:**

- Create: `backend/src/services/generation_status_service.py`
- Test: `backend/tests/test_generation_status_service.py`

- [ ] **Step 1: service 파일을 구현한다**

`backend/src/services/generation_status_service.py`:

```python
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

        estimated_cost = sum(
            value
            for value in [
                latest_run.estimated_cost if latest_run else None,
                *(step.estimated_cost for step in steps),
                *(log.estimated_cost for log in ai_logs),
            ]
            if isinstance(value, (int, float))
        )
        actual_cost = sum(
            value
            for value in [
                latest_run.actual_cost if latest_run else None,
            ]
            if isinstance(value, (int, float))
        )
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
```

- [ ] **Step 2: service 테스트 통과 확인**

Run:

```bash
uv run --project backend pytest backend/tests/test_generation_status_service.py -q
```

Expected:

```text
5 passed
```

---

### Task 3: Operations API 확장

**Files:**

- Modify: `backend/src/api/operations.py`
- Create: `backend/tests/test_generation_operations_api.py`

- [ ] **Step 1: API 테스트 작성**

`backend/tests/test_generation_operations_api.py`:

```python
from fastapi.testclient import TestClient

from src.app import app
from src.db.models import AgentRun, ProductProject


client = TestClient(app)
HEADERS = {
    "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
    "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
}


def test_get_workspace_generation_status(client_db_session, test_workspace, test_user, test_brand):
    project = ProductProject(
        workspace_id=test_workspace.id,
        brand_id=test_brand.id,
        name="상태 대시보드 상품",
        status="processing",
        current_step="copywriting",
    )
    client_db_session.add(project)
    client_db_session.flush()
    client_db_session.add(
        AgentRun(
            id="run-status-api",
            workspace_id=test_workspace.id,
            project_id=project.id,
            mode="real",
            status="running",
            current_stage="copywriting",
            input_snapshot={},
            outputs_json={},
            created_by=test_user.id,
        )
    )
    client_db_session.commit()

    response = client.get("/api/v1/operations/generation-status", headers=HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["running"] >= 1
    assert any(item["project_id"] == project.id for item in payload["projects"])


def test_get_project_generation_status(client_db_session, test_workspace, test_user, test_brand):
    project = ProductProject(
        workspace_id=test_workspace.id,
        brand_id=test_brand.id,
        name="프로젝트 상태 상품",
        status="completed",
        current_step="review_editor",
    )
    client_db_session.add(project)
    client_db_session.commit()

    response = client.get(
        f"/api/v1/operations/projects/{project.id}/generation-status",
        headers=HEADERS,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == project.id
    assert payload["state"] in {"completed", "not_started"}
```

- [ ] **Step 2: 테스트 실패 확인**

Run:

```bash
uv run --project backend pytest backend/tests/test_generation_operations_api.py -q
```

Expected:

```text
404 Not Found
```

- [ ] **Step 3: API 엔드포인트 추가**

`backend/src/api/operations.py` 상단 import에 추가:

```python
from src.services.generation_status_service import GenerationStatusService
```

`backend/src/api/operations.py`의 `router = APIRouter(...)` 아래에 추가:

```python
@router.get("/generation-status")
def get_generation_status_dashboard(
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    workspace = auth_ctx["workspace"]
    return GenerationStatusService(db).get_workspace_status(workspace.id)


@router.get("/projects/{project_id}/generation-status")
def get_project_generation_status(
    project_id: str,
    db: Session = Depends(get_db),
    auth_ctx: dict = Depends(get_current_user_and_workspace),
):
    workspace = auth_ctx["workspace"]
    try:
        return GenerationStatusService(db).get_project_status(project_id, workspace.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
```

- [ ] **Step 4: API 테스트 통과 확인**

Run:

```bash
uv run --project backend pytest backend/tests/test_generation_operations_api.py -q
```

Expected:

```text
2 passed
```

---

### Task 4: AgentRun 생성 중복 guard 추가

**Files:**

- Modify: `backend/src/api/agent_runs.py`
- Create: `backend/tests/test_generation_run_guard.py`

- [ ] **Step 1: 409 guard 테스트 작성**

`backend/tests/test_generation_run_guard.py`:

```python
from fastapi.testclient import TestClient

from src.app import app
from src.db.models import AgentRun, ProductProject


client = TestClient(app)
HEADERS = {
    "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
    "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
}


def test_create_agent_run_blocks_when_same_project_is_running(client_db_session, test_workspace, test_user, test_brand):
    project = ProductProject(
        workspace_id=test_workspace.id,
        brand_id=test_brand.id,
        name="루메나 휴대용 무선 냉각선풍기",
        raw_input_text="무선 냉각선풍기",
        status="processing",
        current_step="copywriting",
    )
    client_db_session.add(project)
    client_db_session.flush()
    client_db_session.add(
        AgentRun(
            id="existing-run",
            workspace_id=test_workspace.id,
            project_id=project.id,
            mode="real",
            status="running",
            current_stage="copywriting",
            input_snapshot={"product_name": project.name},
            outputs_json={},
            created_by=test_user.id,
        )
    )
    client_db_session.commit()

    response = client.post(
        "/api/agent-runs",
        headers=HEADERS,
        json={
            "product_name": "루메나 휴대용 무선 냉각선풍기",
            "description": "무선 냉각선풍기",
            "freeform_input": "무선 냉각선풍기",
            "asset_ids": [],
            "reference_urls": [],
        },
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "generation_already_running"
    assert detail["project_id"] == project.id
    assert detail["run_id"] == "existing-run"


def test_create_agent_run_allows_new_product_when_no_matching_active_project(client_db_session):
    response = client.post(
        "/api/agent-runs",
        headers=HEADERS,
        json={
            "product_name": "새 상품",
            "description": "새 상품 설명",
            "freeform_input": "새 상품 설명",
            "asset_ids": [],
            "reference_urls": [],
        },
    )

    assert response.status_code == 201
    assert response.json()["project_id"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run:

```bash
uv run --project backend pytest backend/tests/test_generation_run_guard.py -q
```

Expected:

```text
FAILED ... assert 201 == 409
```

- [ ] **Step 3: 중복 프로젝트 탐색 함수 추가**

`backend/src/api/agent_runs.py`에 import 추가:

```python
from src.services.generation_status_service import GenerationStatusService
```

`create_agent_run()` 위에 추가:

```python
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
```

- [ ] **Step 4: `create_agent_run()` 시작부에 guard 추가**

`resolved_product_name` 계산 직후 또는 프로젝트 생성 전에 추가:

```python
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
                "result_url": status_payload.get("result_url"),
            },
        )
```

주의: `resolved_product_name`은 현재 URL 수집 이후에 결정된다. guard는 `ProductProject` 생성보다 앞에 있어야 한다.

- [ ] **Step 5: guard 테스트 통과 확인**

Run:

```bash
uv run --project backend pytest backend/tests/test_generation_run_guard.py -q
```

Expected:

```text
2 passed
```

---

### Task 5: Frontend generation status client와 UI 컴포넌트 추가

**Files:**

- Create: `frontend/src/lib/generationStatus.ts`
- Create: `frontend/src/components/GenerationStatusPanel.tsx`
- Create: `frontend/src/components/GenerationDuplicateRunDialog.tsx`

- [ ] **Step 1: API client 타입 작성**

`frontend/src/lib/generationStatus.ts`:

```ts
import { apiUrl } from "@/lib/api";

export type GenerationState =
  | "not_started"
  | "created"
  | "running"
  | "waiting_for_cost_approval"
  | "needs_review"
  | "completed"
  | "failed";

export interface GenerationCost {
  estimated: number;
  actual: number;
  token_input: number;
  token_output: number;
}

export interface GenerationProjectStatus {
  project_id: string;
  project_name: string;
  state: GenerationState;
  current_stage: string;
  failed_stage?: string | null;
  progress_percent: number;
  can_start_new_run: boolean;
  recommended_action: string;
  result_url?: string | null;
  review_url?: string | null;
  cost: GenerationCost;
  last_error?: string | null;
  updated_at: string;
}

export interface GenerationStatusDashboard {
  summary: {
    running: number;
    waiting_for_cost_approval: number;
    needs_review: number;
    completed: number;
    failed: number;
    estimated_cost: number;
    actual_cost: number;
  };
  projects: GenerationProjectStatus[];
}

export function mockHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  return {
    "X-Mock-User-Id": localStorage.getItem("X-Mock-User-Id") || "00000000-0000-0000-0000-000000000001",
    "X-Mock-Workspace-Id": localStorage.getItem("X-Mock-Workspace-Id") || "00000000-0000-0000-0000-000000000002",
  };
}

export async function fetchGenerationStatusDashboard(): Promise<GenerationStatusDashboard> {
  const response = await fetch(apiUrl("/api/v1/operations/generation-status"), {
    headers: mockHeaders(),
  });
  if (!response.ok) {
    throw new Error("작업 상태를 불러오지 못했습니다.");
  }
  return response.json();
}
```

- [ ] **Step 2: 작업 상태 패널 구현**

`frontend/src/components/GenerationStatusPanel.tsx`:

```tsx
"use client";

import React from "react";
import type { GenerationStatusDashboard, GenerationProjectStatus } from "@/lib/generationStatus";

function stateLabel(state: GenerationProjectStatus["state"]): string {
  return {
    not_started: "시작 전",
    created: "생성 준비",
    running: "생성 중",
    waiting_for_cost_approval: "비용 승인 대기",
    needs_review: "검수 필요",
    completed: "완료",
    failed: "실패",
  }[state];
}

function stateClass(state: GenerationProjectStatus["state"]): string {
  if (state === "running") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (state === "failed") return "border-rose-200 bg-rose-50 text-rose-700";
  if (state === "needs_review" || state === "waiting_for_cost_approval") return "border-amber-200 bg-amber-50 text-amber-700";
  if (state === "completed") return "border-blue-200 bg-blue-50 text-blue-700";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

export default function GenerationStatusPanel({
  data,
  onRefresh,
}: {
  data: GenerationStatusDashboard;
  onRefresh: () => void;
}) {
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-extrabold text-white">현재 생성 작업 상태</h2>
          <p className="mt-1 text-xs text-slate-400">
            진행 중인 작업과 비용을 확인해 중복 생성을 막습니다.
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="rounded-xl border border-slate-800 bg-slate-900 px-4 py-2 text-xs font-bold text-slate-200 hover:border-slate-700"
        >
          상태 새로고침
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
        <StatusMetric label="생성 중" value={data.summary.running} />
        <StatusMetric label="비용 승인" value={data.summary.waiting_for_cost_approval} />
        <StatusMetric label="검수 필요" value={data.summary.needs_review} />
        <StatusMetric label="완료" value={data.summary.completed} />
        <StatusMetric label="실패" value={data.summary.failed} />
        <StatusMetric label="실사용 비용" value={`$${data.summary.actual_cost.toFixed(4)}`} />
      </div>

      <div className="overflow-hidden rounded-2xl border border-slate-900 bg-slate-950/30">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-900 bg-slate-900/50 text-xs uppercase tracking-wider text-slate-400">
            <tr>
              <th className="p-4">상품</th>
              <th className="p-4">상태</th>
              <th className="p-4">단계</th>
              <th className="p-4">진행률</th>
              <th className="p-4">비용/토큰</th>
              <th className="p-4">다음 행동</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-900 text-slate-300">
            {data.projects.map((project) => (
              <tr key={project.project_id} className="hover:bg-slate-900/30">
                <td className="p-4 font-bold text-white">{project.project_name}</td>
                <td className="p-4">
                  <span className={`rounded-full border px-2 py-1 text-xs font-bold ${stateClass(project.state)}`}>
                    {stateLabel(project.state)}
                  </span>
                </td>
                <td className="p-4 text-xs text-slate-400">{project.current_stage}</td>
                <td className="p-4">
                  <div className="h-2 w-32 overflow-hidden rounded-full bg-slate-900">
                    <div className="h-full bg-emerald-500" style={{ width: `${project.progress_percent}%` }} />
                  </div>
                  <div className="mt-1 text-[10px] text-slate-500">{project.progress_percent}%</div>
                </td>
                <td className="p-4 text-xs">
                  <div>${project.cost.actual.toFixed(4)} / 예상 ${project.cost.estimated.toFixed(4)}</div>
                  <div className="text-slate-500">
                    in {project.cost.token_input} / out {project.cost.token_output}
                  </div>
                </td>
                <td className="p-4 text-xs">
                  {project.result_url ? (
                    <a className="font-bold text-emerald-400 hover:text-emerald-300" href={project.result_url}>
                      결과 보기
                    </a>
                  ) : project.review_url ? (
                    <a className="font-bold text-amber-400 hover:text-amber-300" href={project.review_url}>
                      검수하기
                    </a>
                  ) : (
                    <span className="text-slate-500">{project.recommended_action}</span>
                  )}
                  {project.last_error ? (
                    <p className="mt-1 max-w-xs truncate text-rose-400">{project.last_error}</p>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function StatusMetric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-slate-900 bg-slate-950/40 p-4">
      <p className="text-[11px] font-bold uppercase tracking-wider text-slate-500">{label}</p>
      <p className="mt-2 text-2xl font-black text-white">{value}</p>
    </div>
  );
}
```

- [ ] **Step 3: 중복 생성 안내 dialog 구현**

`frontend/src/components/GenerationDuplicateRunDialog.tsx`:

```tsx
"use client";

import React from "react";
import { useRouter } from "next/navigation";

interface DuplicateRunDetail {
  code: string;
  message: string;
  project_id: string;
  run_id?: string | null;
  state: string;
  status_url: string;
  result_url?: string | null;
}

export default function GenerationDuplicateRunDialog({
  detail,
  onClose,
}: {
  detail: DuplicateRunDetail;
  onClose: () => void;
}) {
  const router = useRouter();

  return (
    <div role="dialog" aria-modal="true" aria-label="이미 진행 중인 작업" className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4">
      <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl">
        <p className="text-sm font-bold text-amber-700">중복 생성을 막았습니다</p>
        <h2 className="mt-2 text-xl font-black text-slate-950">이미 작업 중인 상세페이지가 있어요</h2>
        <p className="mt-3 text-sm leading-6 text-slate-600">
          {detail.message} 같은 상품을 다시 생성하면 토큰과 이미지 생성 비용이 중복으로 들어갈 수 있습니다.
        </p>
        <div className="mt-5 rounded-xl bg-slate-50 p-4 text-xs text-slate-600">
          <div>상태: {detail.state}</div>
          {detail.run_id ? <div>Run ID: {detail.run_id}</div> : null}
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-bold text-slate-600">
            닫기
          </button>
          {detail.result_url ? (
            <button type="button" onClick={() => router.push(detail.result_url || "/workspace")} className="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-bold text-white">
              결과 화면으로 이동
            </button>
          ) : (
            <button type="button" onClick={() => router.push(detail.status_url)} className="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-bold text-white">
              작업 상태 보기
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export type { DuplicateRunDetail };
```

---

### Task 6: Operations 페이지에 상태 패널 연결

**Files:**

- Modify: `frontend/src/app/workspace/operations/page.tsx`
- Test: `frontend/e2e/generation-status-guard.spec.ts`

- [ ] **Step 1: operations page에 상태 fetch 추가**

`frontend/src/app/workspace/operations/page.tsx` import 추가:

```tsx
import GenerationStatusPanel from "@/components/GenerationStatusPanel";
import { fetchGenerationStatusDashboard, GenerationStatusDashboard } from "@/lib/generationStatus";
```

state 추가:

```tsx
const [generationStatus, setGenerationStatus] = useState<GenerationStatusDashboard | null>(null);
```

fetch 함수 추가:

```tsx
const fetchGenerationStatus = async () => {
  try {
    const data = await fetchGenerationStatusDashboard();
    setGenerationStatus(data);
  } catch {
    setGenerationStatus(null);
  }
};
```

기존 `useEffect` 수정:

```tsx
useEffect(() => {
  fetchStats();
  fetchGenerationStatus();
}, []);
```

header 아래 또는 summary grid 위에 추가:

```tsx
{generationStatus ? (
  <GenerationStatusPanel data={generationStatus} onRefresh={fetchGenerationStatus} />
) : null}
```

- [ ] **Step 2: E2E 테스트 작성**

`frontend/e2e/generation-status-guard.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test("operations page shows generation status dashboard", async ({ page }) => {
  await page.route("**/api/v1/operations/stats", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        summary: {
          total_projects: 1,
          total_ai_jobs: 1,
          ai_job_success_rate: 100,
          ai_job_failure_rate: 0,
          average_ai_duration_seconds: 3,
          total_ai_cost: 0.08,
          total_export_jobs: 0,
          export_job_success_rate: 100,
          export_job_failure_rate: 0,
          average_export_duration_seconds: 0,
        },
        category_stats: {},
        projects: [],
      }),
    });
  });

  await page.route("**/api/v1/operations/generation-status", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        summary: {
          running: 1,
          waiting_for_cost_approval: 0,
          needs_review: 0,
          completed: 0,
          failed: 0,
          estimated_cost: 0.12,
          actual_cost: 0.08,
        },
        projects: [
          {
            project_id: "project-1",
            project_name: "루메나 휴대용 무선 냉각선풍기",
            state: "running",
            current_stage: "image_generation",
            progress_percent: 76,
            can_start_new_run: false,
            recommended_action: "view_status",
            result_url: null,
            review_url: null,
            cost: {
              estimated: 0.12,
              actual: 0.08,
              token_input: 1200,
              token_output: 500,
            },
            last_error: null,
            updated_at: "2026-07-06T12:03:00",
          },
        ],
      }),
    });
  });

  await page.goto("/workspace/operations");

  await expect(page.getByText("현재 생성 작업 상태")).toBeVisible();
  await expect(page.getByText("루메나 휴대용 무선 냉각선풍기")).toBeVisible();
  await expect(page.getByText("생성 중")).toBeVisible();
  await expect(page.getByText("image_generation")).toBeVisible();
  await expect(page.getByText("in 1200 / out 500")).toBeVisible();
});
```

- [ ] **Step 3: E2E 실패 확인**

Run:

```bash
npx.cmd playwright test e2e/generation-status-guard.spec.ts --project=chromium --reporter=line
```

Expected:

```text
FAILED ... 현재 생성 작업 상태 not found
```

- [ ] **Step 4: operations page 수정 후 E2E 통과 확인**

Run:

```bash
npx.cmd playwright test e2e/generation-status-guard.spec.ts --project=chromium --reporter=line
```

Expected:

```text
1 passed
```

---

### Task 7: 생성 화면 중복 실행 dialog 연결

**Files:**

- Modify: `frontend/src/components/AIDetailPageIntake.tsx`
- Modify: `frontend/e2e/generation-status-guard.spec.ts`

- [ ] **Step 1: 409 응답 dialog E2E 추가**

`frontend/e2e/generation-status-guard.spec.ts`에 추가:

```ts
test("intake shows duplicate run dialog when backend blocks repeated generation", async ({ page }) => {
  await page.route("**/api/agent-runs", async (route) => {
    await route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({
        detail: {
          code: "generation_already_running",
          message: "이미 이 상품의 상세페이지 생성이 진행 중입니다.",
          project_id: "project-1",
          run_id: "run-1",
          state: "running",
          status_url: "/workspace/operations?projectId=project-1",
          result_url: null,
        },
      }),
    });
  });

  await page.goto("/workspace");
  await page.getByLabel("상품명").fill("루메나 휴대용 무선 냉각선풍기");
  await page.getByLabel("제품 주요 특징").fill("무선 냉각선풍기");
  await page.getByRole("button", { name: "초안 생성" }).click();

  await expect(page.getByRole("dialog", { name: "이미 진행 중인 작업" })).toBeVisible();
  await expect(page.getByText("중복 생성을 막았습니다")).toBeVisible();
  await expect(page.getByText("작업 상태 보기")).toBeVisible();
});
```

- [ ] **Step 2: 테스트 실패 확인**

Run:

```bash
npx.cmd playwright test e2e/generation-status-guard.spec.ts --project=chromium --reporter=line
```

Expected:

```text
FAILED ... dialog not found
```

- [ ] **Step 3: Intake 컴포넌트에 dialog state 추가**

`frontend/src/components/AIDetailPageIntake.tsx` import 추가:

```tsx
import GenerationDuplicateRunDialog, { DuplicateRunDetail } from "@/components/GenerationDuplicateRunDialog";
```

state 추가:

```tsx
const [duplicateRunDetail, setDuplicateRunDetail] = useState<DuplicateRunDetail | null>(null);
```

`handleSubmit`의 `if (!res.ok)` 블록 수정:

```tsx
      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        if (res.status === 409 && detail?.detail?.code === "generation_already_running") {
          setDuplicateRunDetail(detail.detail);
          return;
        }
        throw new Error("상세페이지 생성 요청에 실패했습니다.");
      }
```

컴포넌트 return 최상단에 dialog 렌더링 추가:

```tsx
{duplicateRunDetail ? (
  <GenerationDuplicateRunDialog
    detail={duplicateRunDetail}
    onClose={() => setDuplicateRunDetail(null)}
  />
) : null}
```

- [ ] **Step 4: E2E 통과 확인**

Run:

```bash
npx.cmd playwright test e2e/generation-status-guard.spec.ts --project=chromium --reporter=line
```

Expected:

```text
2 passed
```

---

## 7. 전체 검증

### Backend

Run:

```bash
uv run --project backend pytest backend/tests/test_generation_status_service.py backend/tests/test_generation_operations_api.py backend/tests/test_generation_run_guard.py -q
```

Expected:

```text
모든 테스트 통과
```

### Frontend build

Run:

```bash
npm.cmd run build
```

Expected:

```text
Compiled successfully
```

### E2E

Run:

```bash
npx.cmd playwright test e2e/generation-status-guard.spec.ts --project=chromium --reporter=line
```

Expected:

```text
2 passed
```

---

## 8. 완료 기준

- `/workspace/operations`에서 현재 생성 작업 상태가 보인다.
- running 작업의 현재 단계, 진행률, 비용, 토큰이 보인다.
- 같은 상품명으로 생성 요청 시 active project가 있으면 409로 차단된다.
- 프론트는 409를 일반 오류가 아니라 “작업 상태 보기” dialog로 보여준다.
- completed 프로젝트는 결과 화면으로 이동할 수 있다.
- failed 프로젝트는 실패 단계와 오류 메시지를 볼 수 있다.
- backend targeted tests 통과.
- frontend build 통과.
- generation status E2E 통과.

---

## 9. 후속 작업 후보

Sprint 69 이후에 이어서 하면 좋은 작업:

1. 실패 단계 재시도 API 실제 구현
2. 이미지 생성 비용 승인 UI
3. 작업 상태 polling 주기 최적화
4. `AgentRunStep.token_usage`를 모든 provider adapter에서 일관되게 기록
5. WebSocket 또는 Server-Sent Events 기반 실시간 진행률
6. “같은 입력 hash” 기반 결과 캐시

