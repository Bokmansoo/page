# Sprint 70 브라우저 다운로드와 클린 Export Render Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PNG/JPG 저장을 Chrome 다운로드 기록에 남는 실제 다운로드로 바꾸고, 저장 이미지에는 Sellform 앱 헤더 없이 상세페이지 본문만 포함되게 만든다.

**Architecture:** 현재 결과 화면의 저장 버튼은 File System Access API로 직접 파일을 쓰고, export render 라우트는 `/workspace` layout 아래에 있어 앱 헤더가 캡처될 수 있다. 이번 Sprint에서는 export 전용 렌더 라우트를 workspace 밖으로 분리하고, 프론트 저장 UX를 브라우저 download 흐름으로 고정한다.

**Tech Stack:** Next.js App Router, React, FastAPI, Playwright screenshot, pytest, Playwright E2E

---

## 1. 해결할 문제

현재 사용자는 `PNG로 저장하기` 또는 `JPG로 저장하기`를 눌렀을 때 다음을 기대한다.

- Chrome 다운로드 기록에 파일이 남는다.
- 다운로드 폴더 또는 브라우저 다운로드 목록에서 파일을 확인할 수 있다.
- 저장된 이미지는 상세페이지 본문만 포함한다.
- `Sellform`, `AI 상세페이지 생성`, `출력 이력`, 워크스페이스 헤더는 저장 이미지에 들어가지 않는다.

하지만 현재 동작은 다음 문제가 있다.

- `showSaveFilePicker()` 기반 직접 저장은 Chrome 다운로드 기록에 남지 않는다.
- export render 경로가 `/workspace/projects/[id]/export-render`라서 workspace layout의 헤더가 섞일 수 있다.
- 사용자는 “저장”과 “다운로드”의 차이를 구분하기 어렵다.

---

## 2. 구현 범위

### 포함

- 브라우저 다운로드 방식으로 PNG/JPG 저장 변경
- export 전용 라우트를 `/workspace` 밖으로 분리
- 백엔드 export render 기본 경로 변경
- 기존 `/workspace/projects/[id]/export-render`는 호환용 redirect 또는 제거 전 안내 처리
- PNG/JPG 각각 다운로드 filename/content-type 검증
- 저장 이미지에 앱 헤더가 포함되지 않는 E2E 검증

### 제외

- 출력 이력 페이지 구현
- 작업 목록 페이지 구현
- PDF/HTML export UX 개선
- 이미지 생성 품질 개선

---

## 3. 파일 구조

### Frontend

- Create: `frontend/src/app/export-render/projects/[id]/page.tsx`
  - workspace layout을 타지 않는 export 전용 상세페이지 렌더 라우트.

- Create 또는 Modify: `frontend/src/app/export-render/projects/[id]/ExportRenderPageClient.tsx`
  - 기존 render client를 재사용하거나 export 전용으로 분리한다.

- Modify: `frontend/src/app/workspace/projects/[id]/export-render/page.tsx`
  - 기존 경로 접근 시 새 경로로 redirect하거나, 테스트 호환을 위해 같은 클라이언트를 렌더하되 layout 제외가 불가능하다는 점을 문서화한다.

- Modify: `frontend/src/components/GeneratedDetailPageResult.tsx`
  - `showSaveFilePicker()` 기본 사용 제거.
  - blob 다운로드를 `<a download>` 방식으로 수행.
  - 버튼 문구를 “PNG로 다운로드”, “JPG로 다운로드”로 정리.

- Test: `frontend/e2e/completed-detail-page-export.spec.ts`
  - PNG/JPG 다운로드 요청과 content type 검증.

- Test: `frontend/e2e/export-render-clean-page.spec.ts`
  - export render 화면에 workspace header가 없는지 검증.

### Backend

- Modify: `backend/src/services/export_service.py`
  - 기본 `SELLFORM_EXPORT_RENDER_PATH`를 `/export-render/projects/{project_id}`로 변경.
  - screenshot 대상은 계속 `[data-detail-page-document='true']`로 유지.

- Modify: `backend/src/api/exports.py`
  - download response의 `Content-Disposition`, `Content-Type`, filename을 format별로 보장.

- Test: `backend/tests/test_export_api.py`
  - PNG/JPG content type과 filename 검증.

---

## 4. 작업 계획

### Task 1: export 전용 라우트를 workspace 밖으로 분리

**Files:**
- Create: `frontend/src/app/export-render/projects/[id]/page.tsx`
- Create: `frontend/src/app/export-render/projects/[id]/ExportRenderPageClient.tsx`
- Modify: `frontend/src/app/workspace/projects/[id]/export-render/page.tsx`

- [ ] **Step 1: 새 export render 라우트 테스트 작성**

테스트 파일에 다음 시나리오를 추가한다.

```ts
test("export render route does not include workspace chrome", async ({ page }) => {
  await page.goto(`/export-render/projects/${projectId}?version_id=${versionId}`);

  await expect(page.locator("[data-detail-page-document='true']")).toBeVisible();
  await expect(page.getByText("Sellform")).toHaveCount(0);
  await expect(page.getByText("AI 상세페이지 생성")).toHaveCount(0);
  await expect(page.getByText("출력 이력")).toHaveCount(0);
});
```

- [ ] **Step 2: 실패 확인**

Run:

```bash
cd frontend
npx.cmd playwright test e2e/export-render-clean-page.spec.ts --project=chromium --reporter=line
```

Expected: 새 라우트가 없어 실패한다.

- [ ] **Step 3: 새 라우트 구현**

`frontend/src/app/export-render/projects/[id]/page.tsx`에서 프로젝트 id와 query를 읽고 기존 상세페이지 렌더 클라이언트를 재사용한다.

```tsx
import { DetailPageRenderClient } from "@/app/workspace/projects/[id]/render/DetailPageRenderClient";

type PageProps = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ version_id?: string }>;
};

export default async function ExportRenderPage({ params, searchParams }: PageProps) {
  const { id } = await params;
  const { version_id: versionId } = await searchParams;

  return (
    <main data-export-render-shell="true">
      <DetailPageRenderClient projectId={id} versionId={versionId ?? null} />
    </main>
  );
}
```

- [ ] **Step 4: 기존 workspace export-render 경로 처리**

기존 경로는 내부 개발용 호환 경로로만 남기거나 새 경로로 redirect한다.

```tsx
import { redirect } from "next/navigation";

type PageProps = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ version_id?: string }>;
};

export default async function LegacyExportRenderPage({ params, searchParams }: PageProps) {
  const { id } = await params;
  const { version_id: versionId } = await searchParams;
  const query = versionId ? `?version_id=${encodeURIComponent(versionId)}` : "";
  redirect(`/export-render/projects/${id}${query}`);
}
```

- [ ] **Step 5: 테스트 통과 확인**

Run:

```bash
cd frontend
npx.cmd playwright test e2e/export-render-clean-page.spec.ts --project=chromium --reporter=line
```

Expected: PASS.

---

### Task 2: 백엔드 export render 기본 경로 변경

**Files:**
- Modify: `backend/src/services/export_service.py`
- Test: `backend/tests/test_export_service.py`

- [ ] **Step 1: 기본 render path 테스트 작성**

```py
def test_default_export_render_path_is_outside_workspace(monkeypatch):
    monkeypatch.delenv("SELLFORM_EXPORT_RENDER_PATH", raising=False)

    path = build_export_render_path(project_id="project-1", version_id="version-1")

    assert path.startswith("/export-render/projects/project-1")
    assert "/workspace/" not in path
    assert "version_id=version-1" in path
```

- [ ] **Step 2: 실패 확인**

Run:

```bash
cd backend
uv run pytest tests/test_export_service.py::test_default_export_render_path_is_outside_workspace -q
```

Expected: 기존 기본값이 `/workspace/...`라 실패한다.

- [ ] **Step 3: 구현**

`export_service.py`에서 기본값을 변경한다.

```py
render_path = os.getenv(
    "SELLFORM_EXPORT_RENDER_PATH",
    "/export-render/projects/{project_id}",
)
```

version query 조립은 기존 로직을 유지한다.

- [ ] **Step 4: 테스트 통과 확인**

Run:

```bash
cd backend
uv run pytest tests/test_export_service.py -q
```

Expected: PASS.

---

### Task 3: 프론트 저장 방식을 브라우저 다운로드로 변경

**Files:**
- Modify: `frontend/src/components/GeneratedDetailPageResult.tsx`
- Test: `frontend/e2e/completed-detail-page-export.spec.ts`

- [ ] **Step 1: 다운로드 동작 테스트 작성**

```ts
const downloadPromise = page.waitForEvent("download");
await page.getByRole("button", { name: "PNG로 다운로드" }).click();
const download = await downloadPromise;

expect(download.suggestedFilename()).toMatch(/\.png$/);
```

JPG도 동일하게 검증한다.

```ts
await page.getByLabel("저장 형식").selectOption("jpg");
const downloadPromise = page.waitForEvent("download");
await page.getByRole("button", { name: "JPG로 다운로드" }).click();
const download = await downloadPromise;

expect(download.suggestedFilename()).toMatch(/\.jpg$/);
```

- [ ] **Step 2: 실패 확인**

Run:

```bash
cd frontend
npx.cmd playwright test e2e/completed-detail-page-export.spec.ts --project=chromium --reporter=line
```

Expected: File System Access API 흐름 때문에 download event가 잡히지 않는다.

- [ ] **Step 3: 구현**

`showSaveFilePicker()` 기본 사용을 제거하고 blob URL anchor 다운로드로 통일한다.

```ts
function downloadBlob(blob: Blob, filename: string) {
  const blobUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = blobUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
}
```

기존 `saveHandle.createWritable()` 흐름은 제거하거나 “다른 이름으로 저장” 별도 옵션으로 분리한다.

- [ ] **Step 4: 버튼 문구 정리**

```tsx
{exportFormat === "png" ? "PNG로 다운로드" : "JPG로 다운로드"}
```

- [ ] **Step 5: 테스트 통과 확인**

Run:

```bash
cd frontend
npx.cmd playwright test e2e/completed-detail-page-export.spec.ts --project=chromium --reporter=line
```

Expected: PASS.

---

### Task 4: 저장 이미지가 상세페이지 본문만 포함하는지 회귀 검증

**Files:**
- Test: `frontend/e2e/completed-detail-page-export.spec.ts`
- Test: `backend/tests/test_export_api.py`

- [ ] **Step 1: 백엔드 다운로드 content type 테스트 작성**

```py
def test_export_download_png_has_attachment_headers(client, project_with_export_asset):
    response = client.get(
        f"/api/v1/projects/{project_with_export_asset.id}/page/export/download/{project_with_export_asset.asset_id}"
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert "attachment" in response.headers["content-disposition"]
    assert ".png" in response.headers["content-disposition"]
```

- [ ] **Step 2: 프론트 E2E에서 다운로드 파일 저장 확인**

```ts
const path = await download.path();
expect(path).toBeTruthy();
```

- [ ] **Step 3: 전체 검증**

Run:

```bash
cd backend
uv run pytest tests/test_export_api.py tests/test_export_service.py -q
```

Run:

```bash
cd frontend
npm.cmd run build
npx.cmd playwright test e2e/completed-detail-page-export.spec.ts e2e/export-render-clean-page.spec.ts --project=chromium --reporter=line
```

Expected: PASS.

---

## 5. 완료 기준

- PNG/JPG 버튼 클릭 시 Playwright `download` event가 발생한다.
- Chrome 다운로드 기록에 남을 수 있는 브라우저 다운로드 방식이다.
- 저장 파일명은 상품명과 확장자를 포함한다.
- 저장 이미지에는 workspace header가 포함되지 않는다.
- export render 라우트는 `/workspace` layout을 타지 않는다.
- backend export 기본 경로가 `/export-render/projects/{project_id}`이다.

---

## 6. 구현 후 다음 단계

Sprint 70 완료 후 Sprint 71에서 출력 이력 페이지를 연결한다. 다운로드가 안정화되지 않으면 출력 이력에서 “다시 다운로드” 기능을 신뢰할 수 없으므로 Sprint 70을 먼저 끝낸다.
