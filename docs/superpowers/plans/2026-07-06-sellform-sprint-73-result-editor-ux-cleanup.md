# Sprint 73 결과 화면과 편집 진입 UX 정리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 결과 화면에서 “고급 편집기로 열기”, “검수하며 다듬기”, “다운로드”, “작업 목록”의 역할을 명확히 분리해 사용자가 다음 행동을 헷갈리지 않게 만든다.

**Architecture:** 결과 화면은 업로드 가능한 상세페이지 확인과 다운로드가 중심이고, 검수 화면은 문구/이미지 후보 수정이 중심이며, 고급 편집기는 레이아웃·섹션 단위 편집이 중심이다. 각 CTA의 목적과 이동 경로를 명확히 분리하고 readiness/error 상태를 버튼 주변에서 바로 설명한다.

**Tech Stack:** Next.js App Router, React, Playwright E2E

---

## 1. 해결할 문제

현재 사용자는 다음을 혼동한다.

- `고급 편집기로 열기`와 `검수하며 다듬기`가 비슷한 페이지로 보인다.
- 다운로드가 안 될 때 왜 막히는지 알기 어렵다.
- 이미지 후보 중 “재생성 필요”가 있는 경우 다음 행동이 불명확하다.
- 결과 화면에서 작업 목록이나 출력 이력으로 돌아가는 경로가 약하다.

---

## 2. 구현 범위

### 포함

- 결과 화면 CTA 재정렬
- `검수하며 다듬기`와 `고급 편집기로 열기` 설명 문구 분리
- 다운로드 readiness blocker 메시지 개선
- 이미지 후보 미완료 상태에서 “검수하며 이미지 보완” CTA 강조
- 작업 목록/출력 이력 링크 추가

### 제외

- 실제 고급 편집기 기능 확장
- AI 문구 품질 개선
- 이미지 생성 provider 변경
- 출력 이력 페이지 신규 구현

---

## 3. 파일 구조

### Frontend

- Modify: `frontend/src/components/GeneratedDetailPageResult.tsx`
  - 결과 화면 하단 sticky CTA와 상단 CTA 문구 정리.

- Modify: `frontend/src/components/DetailPageImageCandidatePanel.tsx`
  - 재생성 필요/적용됨/직접 업로드 상태 문구 정리.

- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
  - `mode=review`와 `mode=advanced`의 헤더/설명 분리.

- Test: `frontend/e2e/result-editor-entrypoints.spec.ts`
  - 각 CTA가 의도한 URL과 mode로 이동하는지 검증.

---

## 4. 작업 계획

### Task 1: 결과 화면 CTA 의미 분리

**Files:**
- Modify: `frontend/src/components/GeneratedDetailPageResult.tsx`
- Test: `frontend/e2e/result-editor-entrypoints.spec.ts`

- [ ] **Step 1: E2E 테스트 작성**

```ts
test("result page shows distinct review and advanced editor actions", async ({ page }) => {
  await page.goto(`/workspace/projects/${projectId}/result`);

  await expect(page.getByRole("link", { name: "검수하며 다듬기" })).toBeVisible();
  await expect(page.getByRole("link", { name: "고급 편집기로 열기" })).toBeVisible();
  await expect(page.getByText("문구와 이미지를 빠르게 확인")).toBeVisible();
  await expect(page.getByText("레이아웃과 섹션을 세밀하게 수정")).toBeVisible();
});
```

- [ ] **Step 2: 실패 확인**

Run:

```bash
cd frontend
npx.cmd playwright test e2e/result-editor-entrypoints.spec.ts --project=chromium --reporter=line
```

Expected: 설명 문구가 없어 실패한다.

- [ ] **Step 3: CTA 문구 구현**

```tsx
<section aria-label="다음 작업">
  <a href={`/workspace/projects/${projectId}/page-editor?mode=review`}>
    검수하며 다듬기
    <span>문구와 이미지를 빠르게 확인하고 업로드 전 오류를 줄입니다.</span>
  </a>
  <a href={`/workspace/projects/${projectId}/page-editor?mode=advanced`}>
    고급 편집기로 열기
    <span>레이아웃과 섹션을 세밀하게 수정합니다.</span>
  </a>
  <a href="/workspace/projects">작업 목록</a>
  <a href="/workspace/exports">출력 이력</a>
</section>
```

- [ ] **Step 4: 테스트 통과 확인**

Run:

```bash
cd frontend
npx.cmd playwright test e2e/result-editor-entrypoints.spec.ts --project=chromium --reporter=line
```

Expected: PASS.

---

### Task 2: review/advanced mode 헤더 분리

**Files:**
- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
- Test: `frontend/e2e/result-editor-entrypoints.spec.ts`

- [ ] **Step 1: mode별 헤더 테스트 작성**

```ts
await page.goto(`/workspace/projects/${projectId}/page-editor?mode=review`);
await expect(page.getByRole("heading", { name: "검수하며 다듬기" })).toBeVisible();
await expect(page.getByText("문구와 이미지 후보를 빠르게 확인")).toBeVisible();

await page.goto(`/workspace/projects/${projectId}/page-editor?mode=advanced`);
await expect(page.getByRole("heading", { name: "고급 편집기" })).toBeVisible();
await expect(page.getByText("섹션 순서와 레이아웃을 세밀하게 조정")).toBeVisible();
```

- [ ] **Step 2: 구현**

```tsx
const isAdvanced = mode === "advanced";

const title = isAdvanced ? "고급 편집기" : "검수하며 다듬기";
const description = isAdvanced
  ? "섹션 순서와 레이아웃을 세밀하게 조정합니다."
  : "문구와 이미지 후보를 빠르게 확인하고 업로드 전 오류를 줄입니다.";
```

- [ ] **Step 3: 검증**

Run:

```bash
cd frontend
npx.cmd playwright test e2e/result-editor-entrypoints.spec.ts --project=chromium --reporter=line
```

Expected: PASS.

---

### Task 3: 다운로드 blocker 메시지 개선

**Files:**
- Modify: `frontend/src/components/GeneratedDetailPageResult.tsx`
- Test: `frontend/e2e/completed-detail-page-export.spec.ts`

- [ ] **Step 1: blocker UX 테스트 작성**

```ts
await page.goto(`/workspace/projects/${projectId}/result`);
await expect(page.getByText("시각 요소 3개 확인 필요")).toBeVisible();
await page.getByRole("button", { name: "PNG로 다운로드" }).click();
await expect(page.getByText("다운로드 전에 이미지 후보를 확인해 주세요.")).toBeVisible();
await expect(page.getByRole("link", { name: "검수하며 이미지 보완" })).toBeVisible();
```

- [ ] **Step 2: 구현**

```tsx
{exportBlockers.length > 0 && (
  <div role="alert">
    <strong>다운로드 전에 이미지 후보를 확인해 주세요.</strong>
    <p>재생성 필요 또는 누락된 이미지가 있으면 상세페이지 품질이 떨어질 수 있습니다.</p>
    <a href={`/workspace/projects/${projectId}/page-editor?mode=review`}>
      검수하며 이미지 보완
    </a>
  </div>
)}
```

- [ ] **Step 3: 검증**

Run:

```bash
cd frontend
npx.cmd playwright test e2e/completed-detail-page-export.spec.ts --project=chromium --reporter=line
```

Expected: PASS.

---

## 5. 완료 기준

- 결과 화면에서 각 CTA의 목적이 문장으로 구분된다.
- `검수하며 다듬기`는 review mode로 이동한다.
- `고급 편집기로 열기`는 advanced mode로 이동한다.
- 다운로드가 막힐 때 이유와 다음 행동이 함께 보인다.
- 작업 목록과 출력 이력으로 돌아갈 수 있다.

---

## 6. 구현 후 다음 단계

Sprint 73 이후에는 실제 상세페이지 품질 개선 흐름으로 돌아간다. 우선순위는 AI 문구 품질, 이미지 재생성 완성도, 그리고 Hookable에서 본 것처럼 “기획 초안 → 섹션 편집 → 상세페이지 생성” 흐름을 더 제품화하는 것이다.
