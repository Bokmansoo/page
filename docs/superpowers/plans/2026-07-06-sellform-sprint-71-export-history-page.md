# Sprint 71 출력 이력 페이지 연결 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 상단 `출력 이력` 메뉴를 alert placeholder가 아닌 실제 출력 이력 페이지로 연결하고, 사용자가 생성한 PNG/JPG/PDF/HTML export 기록을 확인하고 다시 다운로드할 수 있게 만든다.

**Architecture:** 백엔드에는 이미 export job과 asset 정보가 존재하므로, 이를 사용자용 list API로 정리하고 프론트 `/workspace/exports` 페이지에서 표시한다. 결과 화면과 작업 목록에서도 같은 export history 데이터를 재사용할 수 있게 타입과 fetch 함수를 분리한다.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, Next.js App Router, React, Playwright E2E, pytest

---

## 1. 해결할 문제

현재 `출력 이력` 버튼은 다음 alert만 보여준다.

```text
출력 이력 관리는 다음 단계에서 연결됩니다.
```

사용자는 실제로 다음을 기대한다.

- 내가 다운로드 요청했던 PNG/JPG/PDF/HTML 기록을 본다.
- 성공/실패/진행중 상태를 본다.
- 성공한 export는 다시 다운로드한다.
- 실패한 export는 실패 사유와 재시도 경로를 확인한다.

---

## 2. 구현 범위

### 포함

- `/workspace/exports` 페이지 생성
- 상단 `출력 이력` 메뉴를 Link로 변경
- export job list API 정리
- export format, status, filename, created_at, completed_at, project name 표시
- 성공한 파일 “다시 다운로드” 버튼 연결
- 실패 상태에서 실패 사유 표시

### 제외

- 대용량 파일 보관 정책
- 사용량 과금 페이지
- export job 삭제 기능
- 팀/워크스페이스 권한 고도화

---

## 3. 파일 구조

### Backend

- Modify: `backend/src/api/exports.py`
  - 프로젝트 단위 job list 외에 workspace/user 단위 export list endpoint 추가 또는 기존 operations endpoint 재사용.

- Create 또는 Modify: `backend/src/schemas/export_history.py`
  - 출력 이력 응답 DTO.

- Test: `backend/tests/test_export_history_api.py`
  - list, status, download_url 검증.

### Frontend

- Create: `frontend/src/app/workspace/exports/page.tsx`
  - 출력 이력 페이지.

- Create: `frontend/src/lib/exportHistory.ts`
  - API 타입과 fetch 함수.

- Create: `frontend/src/components/ExportHistoryTable.tsx`
  - 출력 이력 테이블.

- Modify: `frontend/src/app/workspace/layout.tsx`
  - alert 제거, `/workspace/exports` Link 연결.

- Test: `frontend/e2e/export-history.spec.ts`
  - 메뉴 이동, 목록 표시, 다시 다운로드 버튼 검증.

---

## 4. 작업 계획

### Task 1: 출력 이력 API 계약 확정

**Files:**
- Create: `backend/src/schemas/export_history.py`
- Modify: `backend/src/api/exports.py`
- Test: `backend/tests/test_export_history_api.py`

- [ ] **Step 1: 실패하는 API 테스트 작성**

```py
def test_list_export_history_returns_recent_exports(client, project_with_export_job):
    response = client.get("/api/v1/page/exports")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["project_id"] == str(project_with_export_job.project_id)
    assert body["items"][0]["format"] in ["png", "jpg", "pdf", "html"]
    assert body["items"][0]["status"] in ["pending", "running", "completed", "failed"]
    assert "download_url" in body["items"][0]
```

- [ ] **Step 2: 실패 확인**

Run:

```bash
cd backend
uv run pytest tests/test_export_history_api.py -q
```

Expected: endpoint가 없어 404.

- [ ] **Step 3: schema 구현**

```py
from pydantic import BaseModel

class ExportHistoryItem(BaseModel):
    id: str
    project_id: str
    project_name: str
    format: str
    status: str
    filename: str | None = None
    content_type: str | None = None
    download_url: str | None = None
    error_message: str | None = None
    created_at: str
    completed_at: str | None = None

class ExportHistoryResponse(BaseModel):
    items: list[ExportHistoryItem]
```

- [ ] **Step 4: endpoint 구현**

```py
@router.get("/page/exports", response_model=ExportHistoryResponse)
def list_export_history(db: Session = Depends(get_db)):
    jobs = (
        db.query(ExportJob)
        .order_by(ExportJob.created_at.desc())
        .limit(100)
        .all()
    )
    return ExportHistoryResponse(items=[to_export_history_item(job) for job in jobs])
```

- [ ] **Step 5: 테스트 통과 확인**

Run:

```bash
cd backend
uv run pytest tests/test_export_history_api.py -q
```

Expected: PASS.

---

### Task 2: 프론트 출력 이력 페이지 구현

**Files:**
- Create: `frontend/src/app/workspace/exports/page.tsx`
- Create: `frontend/src/lib/exportHistory.ts`
- Create: `frontend/src/components/ExportHistoryTable.tsx`
- Test: `frontend/e2e/export-history.spec.ts`

- [ ] **Step 1: E2E 테스트 작성**

```ts
test("user can open export history from top nav", async ({ page }) => {
  await page.goto("/workspace");
  await page.getByRole("link", { name: "출력 이력" }).click();

  await expect(page).toHaveURL(/\/workspace\/exports/);
  await expect(page.getByRole("heading", { name: "출력 이력" })).toBeVisible();
});
```

- [ ] **Step 2: API client 작성**

```ts
export type ExportHistoryItem = {
  id: string;
  project_id: string;
  project_name: string;
  format: "png" | "jpg" | "pdf" | "html";
  status: "pending" | "running" | "completed" | "failed";
  filename: string | null;
  content_type: string | null;
  download_url: string | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
};

export async function fetchExportHistory(): Promise<ExportHistoryItem[]> {
  const response = await fetch("/api/v1/page/exports", { cache: "no-store" });
  if (!response.ok) throw new Error("출력 이력을 불러오지 못했습니다.");
  const body = await response.json();
  return body.items;
}
```

- [ ] **Step 3: 테이블 컴포넌트 구현**

```tsx
export function ExportHistoryTable({ items }: { items: ExportHistoryItem[] }) {
  if (items.length === 0) {
    return <p>아직 출력 이력이 없습니다.</p>;
  }

  return (
    <table>
      <thead>
        <tr>
          <th>상품명</th>
          <th>형식</th>
          <th>상태</th>
          <th>생성일</th>
          <th>다운로드</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.id}>
            <td>{item.project_name}</td>
            <td>{item.format.toUpperCase()}</td>
            <td>{item.status}</td>
            <td>{new Date(item.created_at).toLocaleString("ko-KR")}</td>
            <td>
              {item.status === "completed" && item.download_url ? (
                <a href={item.download_url}>다시 다운로드</a>
              ) : (
                <span>{item.error_message ?? "대기 중"}</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 4: 페이지 연결**

```tsx
export default async function ExportHistoryPage() {
  const items = await fetchExportHistory();

  return (
    <main>
      <h1>출력 이력</h1>
      <p>PNG, JPG 등으로 출력한 상세페이지 기록을 확인하고 다시 다운로드할 수 있습니다.</p>
      <ExportHistoryTable items={items} />
    </main>
  );
}
```

- [ ] **Step 5: E2E 통과 확인**

Run:

```bash
cd frontend
npx.cmd playwright test e2e/export-history.spec.ts --project=chromium --reporter=line
```

Expected: PASS.

---

### Task 3: workspace 상단 메뉴 alert 제거

**Files:**
- Modify: `frontend/src/app/workspace/layout.tsx`
- Test: `frontend/e2e/export-history.spec.ts`

- [ ] **Step 1: alert 미발생 테스트 추가**

```ts
page.on("dialog", async (dialog) => {
  throw new Error(`Unexpected dialog: ${dialog.message()}`);
});

await page.goto("/workspace");
await page.getByRole("link", { name: "출력 이력" }).click();
await expect(page).toHaveURL(/\/workspace\/exports/);
```

- [ ] **Step 2: layout 수정**

`button onClick alert`를 제거하고 `Link`로 변경한다.

```tsx
<Link href="/workspace/exports">출력 이력</Link>
```

- [ ] **Step 3: 검증**

Run:

```bash
cd frontend
npm.cmd run build
npx.cmd playwright test e2e/export-history.spec.ts --project=chromium --reporter=line
```

Expected: PASS.

---

## 5. 완료 기준

- `출력 이력` 클릭 시 alert가 뜨지 않는다.
- `/workspace/exports`로 이동한다.
- export 기록이 최신순으로 보인다.
- 완료된 PNG/JPG는 다시 다운로드할 수 있다.
- 실패한 export는 실패 사유가 보인다.

---

## 6. 구현 후 다음 단계

Sprint 72에서 “내 작업 목록”을 추가하고, 각 작업 카드에서 해당 프로젝트의 출력 이력으로 바로 이동할 수 있게 연결한다.
