# Sellform Sprint 47 Orchestration, Cost Control, And End-To-End QA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the full final-product flow into one reliable orchestration path with progress states, cost-aware image generation, recovery, and QA.

**Architecture:** Add an orchestration service that coordinates intake, understanding, sales strategy, visual package planning, Sprint 44.5 image generation and approval, page generation, export package creation, and marketplace preparation. Track job states and user-visible progress independently from any single AI provider.

**Tech Stack:** FastAPI, SQLAlchemy, existing job logs/status models, Next.js, Playwright.

---

## File Structure

- Create: `backend/src/services/detail_page_orchestrator.py`.
- Create: `backend/src/services/ai_cost_policy.py`.
- Modify: `backend/src/db/models.py` only if existing job/status models cannot represent the orchestration state.
- Create: `backend/tests/test_detail_page_orchestrator.py`.
- Create: `backend/tests/test_ai_cost_policy.py`.
- Create: `frontend/src/components/GenerationProgressPanel.tsx`.
- Create: `frontend/e2e/final-ai-detail-page-md.spec.ts`.

## Tasks

### Task 1: Orchestration States

- [ ] Define states: `intake_received`, `understanding_ready`, `strategy_ready`, `visual_plan_ready`, `image_cost_approval_required`, `images_generating`, `images_ready_for_review`, `copy_ready`, `page_ready`, `package_ready`, `failed_needs_input`.
- [ ] Add tests for normal progression and recoverable failure.

### Task 2: Progress UI

- [ ] Show progress steps in seller language:
  - 상품 이해 중
  - 판매 전략 설계 중
  - 문구 생성 중
  - 이미지 연출 준비 중
  - 이미지 생성 승인 대기
  - AI 이미지 생성 중
  - 생성 이미지 확인 필요
  - 상세페이지 구성 중
  - 판매 패키지 완성 중
- [ ] Avoid showing implementation labels like Figma, renderer, or API before the output stage.

### Task 3: Cost Policy

- [ ] Define cost tiers for text generation, vision analysis, image planning, image generation, and export rendering.
- [ ] Require explicit user action before high-cost image generation.
- [ ] Dispatch only cost-approved Sprint 44.5 image jobs and pause page assembly until required jobs are approved, rejected, or explicitly skipped.
- [ ] Add tests that free/low-cost flows can plan images without generating them.

### Task 4: Recovery

- [ ] If URL extraction fails, continue with manual text/photo input.
- [ ] If image generation is unavailable, continue with existing photos and marked visual needs.
- [ ] If a generated output fails identity validation or is rejected, preserve the source photo and allow regeneration or skip without restarting the full pipeline.
- [ ] If marketplace preparation fails, still allow PNG/web/Figma outputs.

### Task 5: End-To-End QA

- [ ] Add E2E covering photo-only generation.
- [ ] Add E2E covering URL+photo generation.
- [ ] Add E2E covering cost approval, generated-image review, rejection, regeneration, and final approval.
- [ ] Add E2E covering edit command and export panel.
- [ ] Add visual assertions that generated page preview is not blank and has actual section copy.

### Task 6: Verification

- [ ] Run orchestrator and cost policy tests.
- [ ] Run existing page/export/Figma/marketplace regression tests.
- [ ] Run final E2E test.

## Done Criteria

- The full final-product flow can be tested end to end.
- High-cost AI image generation is explicitly gated.
- Approved AI-generated images flow into the final detail page; rejected images do not.
- Failure in one downstream output does not destroy the generated detail page package.
