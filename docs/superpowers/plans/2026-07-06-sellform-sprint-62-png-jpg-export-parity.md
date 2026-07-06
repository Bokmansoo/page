# Sellform Sprint 62 PNG/JPG Export Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** canonical HTML 상세페이지를 미리보기와 동일한 PNG/JPG로 안정적으로 다운로드한다.

**Architecture:** `/render`가 Sprint 61의 `DetailPageDocument`만 렌더링하고, export readiness는 font·모든 이미지·visual contract가 성공한 뒤에만 true가 된다. 백엔드 Playwright worker는 고정 final version을 캡처하며 프론트는 단계별 job 상태를 표시하고 완성 blob을 저장한다.

**Tech Stack:** Next.js, Playwright Python sync API, FastAPI BackgroundTasks, File System Access API, Blob download fallback, pytest, Playwright E2E

---

## 파일 구조

- Create: `frontend/src/lib/exportReadiness.ts`
- Modify: `frontend/src/components/DetailPageDocument.tsx`
- Modify: `frontend/src/components/GeneratedDetailPageResult.tsx`
- Modify: `frontend/src/app/workspace/projects/[id]/render/page.tsx`
- Modify: `backend/src/services/export_service.py`
- Modify: `backend/src/api/exports.py`
- Test: `backend/tests/test_wysiwyg_export_contract.py`
- Test: `backend/tests/test_exports.py`
- Modify: `frontend/e2e/completed-detail-page-export.spec.ts`
- Test: `frontend/e2e/upload-ready-detail-page.spec.ts`

### Task 1: Export readiness가 이미지 오류를 차단

**Files:**
- Create: `frontend/src/lib/exportReadiness.ts`
- Modify: `frontend/src/components/DetailPageDocument.tsx:113-145`
- Test: `frontend/e2e/upload-ready-detail-page.spec.ts`

- [ ] **Step 1: 실패 E2E 작성**

```ts
test("blocks export readiness when a required image fails", async ({ page }) => {
  await page.route("**/api/v1/files/assets/broken", (route) => route.abort());
  await page.goto("/workspace/projects/export-project/render?version_id=version-1");
  await expect(page.locator("html")).toHaveAttribute("data-export-ready", "error");
  await expect(page.getByText("필수 이미지를 불러오지 못했습니다")).toBeVisible();
});
```

- [ ] **Step 2: RED 확인**

Run: `npx.cmd playwright test e2e/upload-ready-detail-page.spec.ts --project=chromium`  
Expected: 현재 error도 resolve해 `true`가 되므로 FAIL.

- [ ] **Step 3: readiness helper 구현**

```ts
export async function waitForExportAssets(): Promise<{ ok: boolean; errors: string[] }> {
  await document.fonts.ready;
  const errors: string[] = [];
  await Promise.all(
    Array.from(document.images).map(
      (image) =>
        new Promise<void>((resolve) => {
          if (image.complete) {
            if (!image.naturalWidth) errors.push(image.currentSrc || image.src);
            resolve();
            return;
          }
          image.addEventListener("load", () => resolve(), { once: true });
          image.addEventListener(
            "error",
            () => {
              errors.push(image.currentSrc || image.src);
              resolve();
            },
            { once: true }
          );
        })
    )
  );
  return { ok: errors.length === 0, errors };
}
```

`DetailPageDocument`는 실패 시:

```ts
document.documentElement.dataset.exportReady = result.ok ? "true" : "error";
document.documentElement.dataset.exportErrors = JSON.stringify(result.errors);
```

- [ ] **Step 4: GREEN 확인**

Run: `npx.cmd playwright test e2e/upload-ready-detail-page.spec.ts --project=chromium`  
Expected: passed.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/lib/exportReadiness.ts frontend/src/components/DetailPageDocument.tsx frontend/e2e/upload-ready-detail-page.spec.ts
git commit -m "fix: block export on failed visual assets"
```

### Task 2: PNG/JPG worker 계약 강화

**Files:**
- Modify: `backend/src/services/export_service.py:13-115`
- Test: `backend/tests/test_wysiwyg_export_contract.py`

- [ ] **Step 1: PNG/JPG와 readiness 오류 테스트 추가**

```python
def _fake_playwright(events, ready="true"):
    class FakeLocator:
        def __init__(self, selector):
            self.selector = selector
        def screenshot(self, **options):
            events.append(("screenshot", options))
            with open(options["path"], "wb") as output:
                output.write(b"image")
        def count(self):
            return 1
        def nth(self, _index):
            return self
        def get_attribute(self, name):
            if name == "data-export-ready":
                return ready
            if name == "data-export-errors":
                return '["broken-image"]'
            return None
    class FakePage:
        def goto(self, *_args, **_kwargs):
            pass
        def wait_for_function(self, *_args, **_kwargs):
            pass
        def locator(self, selector):
            return FakeLocator(selector)
    class FakeBrowser:
        def new_page(self, **_kwargs):
            return FakePage()
        def close(self):
            pass
    class FakeChromium:
        def launch(self, **_kwargs):
            return FakeBrowser()
    return type("FakePlaywright", (), {"chromium": FakeChromium()})()


@pytest.mark.parametrize(
    ("requested", "playwright_type", "suffix"),
    [("png", "png", ".png"), ("jpg", "jpeg", ".jpg")],
)
def test_capture_uses_requested_format(requested, playwright_type, suffix, tmp_path):
    events = []
    result = capture_next_render_export(
        project_id="project-1",
        version_id="version-1",
        output_format=requested,
        output_dir=str(tmp_path),
        playwright=_fake_playwright(events),
    )
    assert result["long_vertical_image"].endswith(suffix)
    assert events[0][1]["type"] == playwright_type


def test_capture_fails_when_render_reports_asset_error(tmp_path):
    with pytest.raises(ExportRenderNotReadyError, match="required visual assets"):
        capture_next_render_export(
            project_id="project-1",
            version_id="version-1",
            output_dir=str(tmp_path),
            playwright=_fake_playwright([], ready="error"),
        )
```

- [ ] **Step 2: RED 확인**

Run: `uv run --project backend pytest backend/tests/test_wysiwyg_export_contract.py -v`  
Expected: error readiness를 구분하지 못해 FAIL.

- [ ] **Step 3: readiness 상태 polling 구현**

```python
class ExportRenderNotReadyError(RuntimeError):
    pass


page.wait_for_function(
    "() => ['true', 'error'].includes(document.documentElement.dataset.exportReady)",
    timeout=30000,
)
ready = page.locator("html").get_attribute("data-export-ready")
if ready == "error":
    errors = page.locator("html").get_attribute("data-export-errors") or "[]"
    raise ExportRenderNotReadyError(f"required visual assets failed: {errors}")
```

JPG 캡처 전 canonical document 배경이 흰색임을 보장하고 `quality=92`를 유지한다.

- [ ] **Step 4: GREEN 확인**

Run: `uv run --project backend pytest backend/tests/test_wysiwyg_export_contract.py -v`  
Expected: all passed.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/services/export_service.py backend/tests/test_wysiwyg_export_contract.py
git commit -m "fix: harden canonical png and jpg capture"
```

### Task 3: Job 상태와 오류 응답 정리

**Files:**
- Modify: `backend/src/db/models.py` (`ExportJob` status 사용)
- Modify: `backend/src/api/exports.py`
- Test: `backend/tests/test_wysiwyg_export_contract.py`

- [ ] **Step 1: 단계별 status 실패 테스트 작성**

```python
def test_export_job_preserves_render_failure(
    db_session,
    testing_session_local,
):
    project, page, user = _create_project_with_page(db_session, "render-failure-project")
    final = DetailPageVersion(
        project_id=project.id,
        name="Final",
        style_key="minimal",
        sections_json={"sections": []},
        is_final=True,
    )
    job = _create_job(db_session, project.id, user.id)
    db_session.add(final)
    db_session.commit()

    with patch("src.api.exports.SessionLocal", testing_session_local), patch(
        "src.services.export_service.capture_next_render_export",
        side_effect=RuntimeError("required visual assets failed: broken-image"),
    ):
        run_export_task(
            project.id,
            page.id,
            job.id,
            "smartstore",
            final_version_id=final.id,
        )

    db_session.refresh(job)
    assert job.status == "failed"
    assert "required visual assets" in job.error_message
```

- [ ] **Step 2: RED 확인**

Run: `uv run --project backend pytest backend/tests/test_wysiwyg_export_contract.py -v`  
Expected: 구체 오류가 보존되지 않아 FAIL.

- [ ] **Step 3: worker 상태 전이 통일**

허용 상태를 `pending -> rendering -> completed | failed`로 제한한다. worker 시작 시
`rendering`, artifact 등록 후에만 `completed`를 저장한다. 실패 시 예외 메시지를
`error_message`에 저장하고 부분 artifact를 제거한다.

- [ ] **Step 4: GREEN 확인**

Run: `uv run --project backend pytest backend/tests/test_wysiwyg_export_contract.py -v`  
Expected: all passed.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/api/exports.py backend/src/db/models.py backend/tests/test_wysiwyg_export_contract.py
git commit -m "fix: expose deterministic export job states"
```

### Task 4: 실제 브라우저 다운로드 UX

**Files:**
- Modify: `frontend/src/components/GeneratedDetailPageResult.tsx:290-405`
- Modify: `frontend/e2e/completed-detail-page-export.spec.ts`

- [ ] **Step 1: PNG/JPG 다운로드 E2E를 parameterize**

```ts
const projectId = "completed-detail-page-project";

const readSavedBlob = (page: Page) =>
  page.evaluate(() => {
    const state = window as typeof window & {
      __savePickerOptions?: { suggestedName?: string };
      __savedBlob?: { type: string; size: number };
    };
    return {
      suggestedName: state.__savePickerOptions?.suggestedName,
      type: state.__savedBlob?.type,
    };
  });

for (const format of ["png", "jpg"] as const) {
  test(`downloads canonical ${format}`, async ({ page }) => {
    // API fixture는 format에 맞는 content-type과 filename을 반환한다.
    await page.goto(`/workspace/projects/${projectId}/result`);
    await page.getByLabel("저장 형식").selectOption(format);
    await page.getByRole("button", { name: new RegExp(format, "i") }).click();
    await expect.poll(() => readSavedBlob(page)).toEqual({
      suggestedName: `상품명.${format}`,
      type: format === "jpg" ? "image/jpeg" : "image/png",
    });
  });
}
```

- [ ] **Step 2: RED 확인**

Run: `npx.cmd playwright test e2e/completed-detail-page-export.spec.ts --project=chromium`  
Expected: JPG fixture/저장 검증이 없어 FAIL.

- [ ] **Step 3: 진행 상태와 실패 복구 구현**

프론트 상태:

```ts
type ExportStage = "idle" | "finalizing" | "rendering" | "downloading" | "saving";
```

각 fetch 전 stage를 갱신한다. 오류 시 선택한 format과 메시지를 유지하고 재시도 버튼을
표시한다. 버튼 활성 조건은 Sprint 61의 `invalidVisualCount === 0`과 identity/grounding
blocker가 없는 경우다.

- [ ] **Step 4: GREEN 확인**

Run:

```powershell
npx.cmd playwright test e2e/completed-detail-page-export.spec.ts e2e/upload-ready-detail-page.spec.ts --project=chromium
```

Expected: PNG/JPG tests passed.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/GeneratedDetailPageResult.tsx frontend/e2e/completed-detail-page-export.spec.ts
git commit -m "fix: download canonical png and jpg exports"
```

### Task 5: Sprint 62 전체 검증

- [ ] **Step 1: Backend**

```powershell
uv run --project backend pytest backend/tests/test_exports.py backend/tests/test_wysiwyg_export_contract.py -v
```

- [ ] **Step 2: Frontend**

```powershell
cd frontend
npm.cmd run lint
npm.cmd run build
npx.cmd playwright test e2e/completed-detail-page-export.spec.ts e2e/upload-ready-detail-page.spec.ts --project=chromium
```

Expected: lint error 0, build success, selected E2E all passed.
