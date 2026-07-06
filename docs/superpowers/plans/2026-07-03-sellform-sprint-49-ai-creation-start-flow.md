# Sellform Sprint 49 AI Creation Start Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/workspace`의 첫 경험을 편집기 목록이 아니라 흰 바탕 AI 상세페이지 생성 시작 화면으로 바꾼다.

**Architecture:** 프론트엔드는 사진/URL/상품명/설명 입력을 받는 밝은 제작형 홈페이지 화면을 제공하고, 백엔드는 해당 입력으로 `intake` 상태의 프로젝트와 agent run을 만든다. 실제 AI 실행은 Sprint 50부터이며, Sprint 49는 흰 바탕 입력 UX, 단일 CTA, 생성 진행 shell만 만든다. 화면 톤은 남색+화이트 대시보드가 아니라 화이트 기반에 소프트 민트/그린 포인트를 얹은 AI 생성기 경험으로 잡는다.

**Tech Stack:** Next.js App Router, React, FastAPI, SQLAlchemy, pytest, Playwright.

---

## File Structure

- Modify: `frontend/src/app/workspace/page.tsx`
- Create: `frontend/src/components/AIDetailPageIntake.tsx`
- Create: `frontend/src/components/GenerationProgressShell.tsx`
- Create: `frontend/e2e/ai-creation-start-flow.spec.ts`
- Modify: `backend/src/api/projects.py`
- Create: `backend/src/api/agent_runs.py`
- Modify: `backend/src/app.py`
- Test: `backend/tests/test_agent_run_api.py`

## Tasks

### Task 1: Agent run 생성 API 추가

**Files:**
- Create: `backend/src/api/agent_runs.py`
- Modify: `backend/src/app.py`
- Test: `backend/tests/test_agent_run_api.py`

- [ ] **Step 1: Write failing API test**

```python
def test_create_agent_run_from_product_name(client, auth_headers):
    response = client.post(
        "/api/agent-runs",
        headers=auth_headers,
        json={"product_name": "유아 자전거", "description": "보조 바퀴가 있는 첫 자전거"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["current_stage"] == "intake"
    assert data["mode"] == "mock"
    assert data["product_input"]["product_name"] == "유아 자전거"
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && uv run pytest tests/test_agent_run_api.py -v`  
Expected: FAIL because endpoint does not exist.

- [ ] **Step 3: Implement endpoint**

Add `POST /api/agent-runs` that creates a project or run record using existing project persistence. If no dedicated table exists yet, store initial state in project metadata compatible with Sprint 48 `AgentRunState`.

- [ ] **Step 4: Run test**

Run: `cd backend && uv run pytest tests/test_agent_run_api.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/api/agent_runs.py backend/src/app.py backend/tests/test_agent_run_api.py
git commit -m "feat: add agent run intake api"
```

### Task 2: AI 상세페이지 입력 컴포넌트 추가

**Files:**
- Create: `frontend/src/components/AIDetailPageIntake.tsx`
- Modify: `frontend/src/app/workspace/page.tsx`

- [ ] **Step 1: Add component testable UI**

Create a light UI with a white or near-white page background. The screen must feel like an AI detail page creation service, not a dark admin editor.

Visual direction:

- Use a white or near-white full-page background.
- Use soft mint/green as the main brand accent for badges, trust cues, and light highlights.
- Use blue only as a secondary action/progress accent.
- Do not let dark navy dominate the screen.
- Do not show a dark left sidebar on the first creation screen.
- If workspace navigation must remain available, move it to a light top header or low-emphasis secondary entry.
- The first impression should be closer to an easy AI creation service than to an admin dashboard.

- headline: `상품 사진이나 URL을 넣으면 AI가 상세페이지를 만들어드려요.`
- subcopy: `상품을 어떻게 설명해야 할지 몰라도 괜찮아요. AI가 판매 포인트, 문구, 이미지 연출 방향까지 먼저 제안합니다.`
- file input label: `상품 사진`
- URL input placeholder: `상품 URL`
- product name input placeholder: `상품명`
- description textarea placeholder: `간단한 설명`
- preset section label: `상세페이지 분위기 선택`
- preset chips: `깔끔한`, `감성적인`, `프리미엄`, `실용 강조`, `선물용`
- CTA: `AI 상세페이지 만들기`

The visual hierarchy must be:

1. Sellform brand and `AI 상세페이지` as the active product context.
2. Centered headline and short subcopy.
3. One large white input card with upload, URL, product name, description, and preset chips.
4. A single primary CTA.
5. A low-emphasis preview of generation steps: `상품 분석`, `판매 전략`, `문구 작성`, `이미지 기획`, `상세페이지 조립`.

Do not show the page editor, section list, Figma export, marketplace settings, or version history on the first workspace screen.
Do not show a dark workspace sidebar as the dominant frame on the first workspace screen.

- [ ] **Step 2: Wire `/workspace` to use the component**

Replace editor-first content in `frontend/src/app/workspace/page.tsx` with the intake component. For this start screen, do not preserve a dark sidebar if it makes the page feel like an admin workspace. Preserve only the minimum navigation needed through a light header or low-emphasis links.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/workspace/page.tsx frontend/src/components/AIDetailPageIntake.tsx
git commit -m "feat: show ai detail page intake first"
```

### Task 3: 생성 진행 shell 추가

**Files:**
- Create: `frontend/src/components/GenerationProgressShell.tsx`
- Modify: `frontend/src/components/AIDetailPageIntake.tsx`

- [ ] **Step 1: Add progress shell**

The shell must show these labels:

- 상품 이해
- 판매 방향 추천
- 상세페이지 구조 설계
- 문구 생성
- 이미지 연출 기획
- 이미지 생성
- 상세페이지 조립
- 검수

- [ ] **Step 2: Route after intake submit**

After successful `POST /api/agent-runs`, show the progress shell or navigate to the project generation route if one already exists.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/AIDetailPageIntake.tsx frontend/src/components/GenerationProgressShell.tsx
git commit -m "feat: add generation progress shell"
```

### Task 4: E2E 검증

**Files:**
- Create: `frontend/e2e/ai-creation-start-flow.spec.ts`

- [ ] **Step 1: Write Playwright test**

```ts
import { test, expect } from "@playwright/test";

test("workspace starts with AI detail page intake", async ({ page }) => {
  await page.goto("/workspace");
  await expect(page.getByText("상품 사진이나 URL을 넣으면 AI가 상세페이지를 만들어드려요.")).toBeVisible();
  await page.getByPlaceholder("상품명").fill("유아 자전거");
  await page.getByPlaceholder("간단한 설명").fill("보조 바퀴가 있는 첫 자전거");
  await page.getByRole("button", { name: "AI 상세페이지 만들기" }).click();
  await expect(page.getByText("상품 이해")).toBeVisible();
});
```

- [ ] **Step 2: Run E2E**

Run: `cd frontend && npm.cmd test -- --grep "workspace starts with AI detail page intake"`  
Expected: PASS after backend/frontend test servers are running.

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/ai-creation-start-flow.spec.ts
git commit -m "test: cover ai creation start flow"
```

## Done Criteria

- UI implementation follows `DESIGN.md` as the source of truth.
- The start screen feels like a bright solo-seller detail page creation service, not an AI technology dashboard.
- Purple/blue AI gradients, excessive sparkle icons, generic SaaS hero sections, and editor-first layouts are not used.
- `/workspace` starts with a white or near-white AI 상세페이지 만들기 input screen, not the dark editor.
- `/workspace` does not show a dark navy sidebar as the dominant first-screen frame.
- Main accent color is soft mint/green, with blue used only as secondary emphasis.
- The first screen has one dominant CTA: `AI 상세페이지 만들기`.
- The first screen shows upload, URL, product name, description, and mood preset inputs in one focused creation card.
- The first screen does not show section editing, Figma export, marketplace registration, version history, or final-page editor controls.
- The user can submit product name/description and create an intake run.
- Progress shell appears without calling real AI APIs.
- Backend API and frontend E2E tests pass.
