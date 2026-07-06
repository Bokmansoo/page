# Sellform Sprint 53 Review Editor Reframe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 상세페이지 편집기를 첫 화면이 아니라 생성 이후 검수/보완 도구로 재정의한다.

**Architecture:** `/page-editor`는 `page_assembly`가 존재하는 프로젝트에서만 열리도록 하고, 좌측 전략/섹션 아웃라인, 중앙 모바일 상세페이지 미리보기, 우측 AI 편집 명령 구조로 재배치한다. 직접 편집은 유지하되 기본 상호작용은 AI 명령형 수정이다. 편집기는 어두운 관리자 도구가 아니라, AI가 만든 상세페이지를 밝은 캔버스에서 검수하고 다듬는 화면이어야 한다.

**Tech Stack:** Next.js App Router, React components, existing page version service, FastAPI edit endpoints, Playwright.

---

## File Structure

- Create: `frontend/src/app/workspace/projects/[id]/result/page.tsx`
- Create: `frontend/src/components/GeneratedDetailPageResult.tsx`
- Modify: `frontend/src/components/GenerationProgressShell.tsx`
- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
- Create: `frontend/src/components/ReviewEditorLayout.tsx`
- Create: `frontend/src/components/AiEditCommandPanel.tsx`
- Create: `frontend/src/components/GeneratedPageOutline.tsx`
- Modify: `backend/src/api/pages.py`
- Modify: `backend/src/services/page_version_service.py`
- Test: `backend/tests/test_ai_edit_command_api.py`
- Create: `frontend/e2e/review-editor-reframe.spec.ts`

## Tasks

### Task 0: 생성 완료 CTA를 white-first 결과 화면으로 연결

**Files:**
- Create: `frontend/src/app/workspace/projects/[id]/result/page.tsx`
- Create: `frontend/src/components/GeneratedDetailPageResult.tsx`
- Modify: `frontend/src/components/GenerationProgressShell.tsx`
- Create/Modify: `frontend/e2e/review-editor-reframe.spec.ts`

- [ ] **Step 1: Add E2E test for the default result path**

```ts
import { test, expect } from "@playwright/test";

test("generated detail page CTA opens white-first result screen", async ({ page }) => {
  await page.goto("/workspace");

  await page.getByLabel("상품명").fill("삼성 삼탠바이미 32인치 스마트모니터 TV + 무빙 스탠드");
  await page.getByRole("button", { name: "AI 상세페이지 만들기" }).click();
  await page.getByRole("button", { name: "생성된 상세페이지 보기" }).click();

  await expect(page).toHaveURL(/\/workspace\/projects\/.+\/result$/);
  await expect(page.getByText("생성된 상세페이지 초안")).toBeVisible();
  await expect(page.getByText("삼탠바이미")).toBeVisible();
  await expect(page.getByText("셀폼 상세페이지 가이드 에디터 1.0")).not.toBeVisible();
});
```

- [ ] **Step 2: Run E2E to verify failure**

Run: `cd frontend && npm.cmd test -- --grep "white-first result screen"`  
Expected: FAIL because generated result currently may route to the dark `/page-editor` flow.

- [ ] **Step 3: Implement white-first generated result route**

Create `GeneratedDetailPageResult` with:

- white-first page background
- centered detail page preview as the primary object
- calm green/mint status and action states
- uploaded/URL/mock image source labels
- seller-friendly copy such as `생성된 상세페이지 초안`
- primary action: `PNG로 저장하기` or `검수하며 다듬기`
- secondary action: `고급 편집기로 열기`

Do not show the dark dashboard frame, dark sidebar, or editor-first workflow on this default result screen.

- [ ] **Step 4: Change the generation completion CTA**

`GenerationProgressShell` must send `생성된 상세페이지 보기` to:

`/workspace/projects/{projectId}/result`

not directly to:

`/workspace/projects/{projectId}/page-editor`

- [ ] **Step 5: Keep page-editor as an advanced tool**

The dark or complex editor route may remain for advanced editing, but it must be reachable only from an explicit secondary action such as `고급 편집기로 열기`.

- [ ] **Step 6: Run E2E**

Run: `cd frontend && npm.cmd test -- --grep "white-first result screen"`  
Expected: PASS.

### Task 1: 생성 전 편집기 진입 차단

**Files:**
- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
- Create: `frontend/e2e/review-editor-reframe.spec.ts`

- [ ] **Step 1: Add E2E test**

```ts
import { test, expect } from "@playwright/test";

test("page editor redirects or explains when no generated page exists", async ({ page }) => {
  await page.goto("/workspace/projects/mock-project-without-assembly/page-editor");
  await expect(page.getByText("아직 생성된 상세페이지가 없습니다")).toBeVisible();
  await expect(page.getByRole("link", { name: "AI 상세페이지 만들기" })).toBeVisible();
});
```

- [ ] **Step 2: Run E2E to verify failure**

Run: `cd frontend && npm.cmd test -- --grep "no generated page exists"`  
Expected: FAIL because guard UI does not exist.

- [ ] **Step 3: Implement guard**

If the project has no `page_assembly` or final page version, show the empty-state message and link back to intake/generation.

- [ ] **Step 4: Run E2E**

Run: `cd frontend && npm.cmd test -- --grep "no generated page exists"`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/workspace/projects/[id]/page-editor/page.tsx frontend/e2e/review-editor-reframe.spec.ts
git commit -m "feat: gate editor behind generated page"
```

### Task 2: 검수 편집기 레이아웃 추가

**Files:**
- Create: `frontend/src/components/ReviewEditorLayout.tsx`
- Create: `frontend/src/components/GeneratedPageOutline.tsx`
- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`

- [ ] **Step 1: Implement layout**

Use:

- left: strategy and section outline
- center: mobile detail page preview
- right: edit command panel placeholder

The heading should read `생성된 상세페이지 검수`.

Visual direction:

- Keep the generated page preview on a white or near-white canvas.
- Use soft mint/green for positive AI status, selected state, and safe review cues.
- Use blue only for secondary progress or action emphasis.
- Dark navy must not be used as a full-page background or dominant sidebar color.
- If a side panel needs contrast, use light gray/white panels with dark text instead of a heavy navy block.
- The screen should feel like "AI가 만든 결과를 다듬는 검수 화면", not a complex design/admin editor.

- [ ] **Step 2: Add outline component**

`GeneratedPageOutline` receives `sections` and displays section title, role, warning count.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ReviewEditorLayout.tsx frontend/src/components/GeneratedPageOutline.tsx frontend/src/app/workspace/projects/[id]/page-editor/page.tsx
git commit -m "feat: add generated page review editor layout"
```

### Task 3: AI 편집 명령 API 추가

**Files:**
- Modify: `backend/src/api/pages.py`
- Modify: `backend/src/services/page_version_service.py`
- Test: `backend/tests/test_ai_edit_command_api.py`

- [ ] **Step 1: Write failing API test**

```python
def test_ai_edit_command_creates_new_page_version(client, auth_headers, generated_project):
    response = client.post(
        f"/api/projects/{generated_project.id}/pages/ai-edit",
        headers=auth_headers,
        json={"section_id": "hero", "command": "제목을 더 자연스럽게 바꿔줘"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["version_id"]
    assert data["status"] in {"mock_applied", "applied"}
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && uv run pytest tests/test_ai_edit_command_api.py -v`  
Expected: FAIL because endpoint does not exist.

- [ ] **Step 3: Implement mock edit command**

In mock mode, create a new page version with a deterministic note such as `[AI 수정됨]`. Real LLM rewriting is not required in Sprint 53.

- [ ] **Step 4: Run test**

Run: `cd backend && uv run pytest tests/test_ai_edit_command_api.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/api/pages.py backend/src/services/page_version_service.py backend/tests/test_ai_edit_command_api.py
git commit -m "feat: add ai edit command endpoint"
```

### Task 4: AI 편집 명령 패널 연결

**Files:**
- Create: `frontend/src/components/AiEditCommandPanel.tsx`
- Modify: `frontend/src/components/ReviewEditorLayout.tsx`
- Modify: `frontend/e2e/review-editor-reframe.spec.ts`

- [ ] **Step 1: Implement command panel**

Buttons:

- 제목을 더 강하게
- 더 자연스럽게
- 과장 표현 줄이기
- 이미지 장면 다시 만들기
- 이 섹션 앞으로 이동
- 근거 추가하기

Also include a free text command input.

- [ ] **Step 2: Add E2E assertion**

```ts
await expect(page.getByRole("button", { name: "더 자연스럽게" })).toBeVisible();
await expect(page.getByPlaceholder("AI에게 수정 요청하기")).toBeVisible();
```

- [ ] **Step 3: Run E2E**

Run: `cd frontend && npm.cmd test -- --grep "review editor"`  
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AiEditCommandPanel.tsx frontend/src/components/ReviewEditorLayout.tsx frontend/e2e/review-editor-reframe.spec.ts
git commit -m "feat: add ai edit command panel"
```

## Done Criteria

- Review editor follows `DESIGN.md`: generated detail page preview remains the primary object, side panels stay light and supportive, and AI controls use seller-friendly language.
- Purple/blue AI gradients, excessive sparkle icons, and generic SaaS editor framing are not used.
- Editor is no longer the first product surface.
- Editor opens only for generated page drafts.
- Users see strategy outline, mobile preview, and AI edit commands.
- Mock edit command creates a new version without real LLM calls.
- Review editor uses a bright canvas-first visual system, not a dark navy dashboard frame.
- Dark colors are limited to text, subtle borders, small labels, or optional advanced panels.
- After generation, the default `생성된 상세페이지 보기` flow opens the white-first result screen, not the dark `/page-editor`.
- The dark/advanced editor is available only through an explicit secondary action.
- Result screen must show the generated detail page preview as the main object and preserve product-specific mock output from Sprint 52.
