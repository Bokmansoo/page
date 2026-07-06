# Sprint 72 내 상세페이지 작업 목록 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사용자가 지금까지 생성한 상세페이지 작업을 한 곳에서 확인하고, 결과 보기·검수하기·다시 다운로드로 재진입할 수 있는 작업 목록을 만든다.

**Architecture:** 프로젝트와 최신 상세페이지 버전, 생성 상태, 대표 썸네일, 마지막 export 상태를 하나의 작업 카드 DTO로 합친다. 프론트는 `/workspace/projects` 또는 `/workspace/my-pages`에서 이 목록을 보여주고 상단 메뉴에 “작업 목록”을 추가한다.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, Next.js App Router, React, Playwright E2E, pytest

---

## 1. 해결할 문제

현재 사용자는 생성했던 상세페이지를 다시 찾기 어렵다.

필요한 UX는 다음과 같다.

- 내가 만든 상세페이지 목록을 본다.
- 생성 중/검수 필요/완료/실패 상태를 본다.
- 결과 화면으로 다시 들어간다.
- 검수하며 다듬기 화면으로 다시 들어간다.
- 마지막으로 다운로드한 출력물을 다시 받을 수 있다.

---

## 2. 구현 범위

### 포함

- `/workspace/projects` 작업 목록 페이지
- 상단 메뉴에 “작업 목록” 추가
- 작업 카드에 상품명, 상태, 업데이트 시간, 썸네일, CTA 표시
- 결과 보기, 검수하며 다듬기, 출력 이력 이동
- 목록 empty state 표시

### 제외

- 프로젝트 삭제
- 프로젝트 복제
- 검색/필터 고도화
- 팀원별 권한 필터
- 대량 선택/일괄 다운로드

---

## 3. 파일 구조

### Backend

- Create: `backend/src/schemas/project_worklist.py`
  - 작업 목록 DTO.

- Modify: `backend/src/api/projects.py`
  - `GET /api/v1/projects/worklist` 추가.

- Test: `backend/tests/test_project_worklist_api.py`
  - 상태별 작업 목록 응답 검증.

### Frontend

- Create: `frontend/src/app/workspace/projects/page.tsx`
  - 작업 목록 페이지.

- Create: `frontend/src/lib/projectWorklist.ts`
  - API 타입과 fetch 함수.

- Create: `frontend/src/components/ProjectWorklist.tsx`
  - 카드 리스트.

- Modify: `frontend/src/app/workspace/layout.tsx`
  - “작업 목록” 메뉴 추가.

- Test: `frontend/e2e/project-worklist.spec.ts`
  - 목록 표시와 CTA 이동 검증.

---

## 4. 작업 계획

### Task 1: 작업 목록 API 구현

**Files:**
- Create: `backend/src/schemas/project_worklist.py`
- Modify: `backend/src/api/projects.py`
- Test: `backend/tests/test_project_worklist_api.py`

- [ ] **Step 1: 실패하는 API 테스트 작성**

```py
def test_project_worklist_returns_generated_pages(client, project_with_final_page):
    response = client.get("/api/v1/projects/worklist")

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) >= 1
    item = body["items"][0]
    assert item["project_id"] == str(project_with_final_page.id)
    assert item["project_name"]
    assert item["status"] in ["generating", "needs_review", "completed", "failed"]
    assert item["result_url"].startswith("/workspace/projects/")
    assert item["review_url"].startswith("/workspace/projects/")
```

- [ ] **Step 2: 실패 확인**

Run:

```bash
cd backend
uv run pytest tests/test_project_worklist_api.py -q
```

Expected: endpoint가 없어 404.

- [ ] **Step 3: schema 작성**

```py
from pydantic import BaseModel

class ProjectWorklistItem(BaseModel):
    project_id: str
    project_name: str
    status: str
    thumbnail_url: str | None = None
    result_url: str | None = None
    review_url: str | None = None
    export_history_url: str
    last_export_status: str | None = None
    updated_at: str

class ProjectWorklistResponse(BaseModel):
    items: list[ProjectWorklistItem]
```

- [ ] **Step 4: endpoint 구현**

```py
@router.get("/projects/worklist", response_model=ProjectWorklistResponse)
def list_project_worklist(db: Session = Depends(get_db)):
    projects = db.query(ProductProject).order_by(ProductProject.updated_at.desc()).limit(100).all()
    return ProjectWorklistResponse(items=[to_worklist_item(project) for project in projects])
```

- [ ] **Step 5: 테스트 통과 확인**

Run:

```bash
cd backend
uv run pytest tests/test_project_worklist_api.py -q
```

Expected: PASS.

---

### Task 2: 작업 목록 프론트 페이지 구현

**Files:**
- Create: `frontend/src/app/workspace/projects/page.tsx`
- Create: `frontend/src/lib/projectWorklist.ts`
- Create: `frontend/src/components/ProjectWorklist.tsx`
- Test: `frontend/e2e/project-worklist.spec.ts`

- [ ] **Step 1: E2E 테스트 작성**

```ts
test("user can view generated detail page worklist", async ({ page }) => {
  await page.goto("/workspace/projects");

  await expect(page.getByRole("heading", { name: "작업 목록" })).toBeVisible();
  await expect(page.getByText("루메나")).toBeVisible();
  await expect(page.getByRole("link", { name: "결과 보기" })).toBeVisible();
  await expect(page.getByRole("link", { name: "검수하며 다듬기" })).toBeVisible();
});
```

- [ ] **Step 2: API client 작성**

```ts
export type ProjectWorklistItem = {
  project_id: string;
  project_name: string;
  status: "generating" | "needs_review" | "completed" | "failed";
  thumbnail_url: string | null;
  result_url: string | null;
  review_url: string | null;
  export_history_url: string;
  last_export_status: string | null;
  updated_at: string;
};

export async function fetchProjectWorklist(): Promise<ProjectWorklistItem[]> {
  const response = await fetch("/api/v1/projects/worklist", { cache: "no-store" });
  if (!response.ok) throw new Error("작업 목록을 불러오지 못했습니다.");
  const body = await response.json();
  return body.items;
}
```

- [ ] **Step 3: 카드 컴포넌트 구현**

```tsx
export function ProjectWorklist({ items }: { items: ProjectWorklistItem[] }) {
  if (items.length === 0) {
    return (
      <section>
        <h2>아직 생성한 상세페이지가 없습니다.</h2>
        <a href="/workspace">첫 상세페이지 만들기</a>
      </section>
    );
  }

  return (
    <div>
      {items.map((item) => (
        <article key={item.project_id}>
          <h2>{item.project_name}</h2>
          <p>{item.status}</p>
          <p>{new Date(item.updated_at).toLocaleString("ko-KR")}</p>
          {item.result_url && <a href={item.result_url}>결과 보기</a>}
          {item.review_url && <a href={item.review_url}>검수하며 다듬기</a>}
          <a href={item.export_history_url}>출력 이력</a>
        </article>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: 페이지 연결**

```tsx
export default async function WorkspaceProjectsPage() {
  const items = await fetchProjectWorklist();

  return (
    <main>
      <h1>작업 목록</h1>
      <p>생성한 상세페이지를 다시 확인하고 수정하거나 다운로드할 수 있습니다.</p>
      <ProjectWorklist items={items} />
    </main>
  );
}
```

- [ ] **Step 5: 테스트 통과 확인**

Run:

```bash
cd frontend
npx.cmd playwright test e2e/project-worklist.spec.ts --project=chromium --reporter=line
```

Expected: PASS.

---

### Task 3: 상단 메뉴에 작업 목록 연결

**Files:**
- Modify: `frontend/src/app/workspace/layout.tsx`
- Test: `frontend/e2e/project-worklist.spec.ts`

- [ ] **Step 1: 메뉴 이동 테스트 추가**

```ts
await page.goto("/workspace");
await page.getByRole("link", { name: "작업 목록" }).click();
await expect(page).toHaveURL(/\/workspace\/projects/);
```

- [ ] **Step 2: layout 수정**

```tsx
<Link href="/workspace/projects">작업 목록</Link>
```

- [ ] **Step 3: 검증**

Run:

```bash
cd frontend
npm.cmd run build
npx.cmd playwright test e2e/project-worklist.spec.ts --project=chromium --reporter=line
```

Expected: PASS.

---

## 5. 완료 기준

- `/workspace/projects`에서 내가 만든 상세페이지 목록을 볼 수 있다.
- 결과 보기, 검수하며 다듬기, 출력 이력으로 이동할 수 있다.
- 상단 메뉴에서 작업 목록으로 이동할 수 있다.
- 작업이 없을 때 empty state가 보인다.

---

## 6. 구현 후 다음 단계

Sprint 73에서 결과 화면과 검수/고급 편집기 진입 UX를 정리해 사용자가 각 버튼의 의미를 혼동하지 않게 만든다.
