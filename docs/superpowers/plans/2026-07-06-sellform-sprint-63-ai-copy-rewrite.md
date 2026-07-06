# Sellform Sprint 63 AI Copy Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** “선택한 섹션 다듬기”의 모든 버튼과 직접 요청이 판매 문구를 실제로 재작성하고, 사용자가 전후 비교 후 적용할 수 있게 한다.

**Architecture:** 새 `CopyRewriteService`가 command, section copy, confirmed facts, forbidden claims를 받아 mutation 없는 proposal을 반환한다. 프론트가 proposal을 비교 표시하고 적용 시 기존 page PATCH를 호출해 version을 생성한다.

**Tech Stack:** FastAPI, Pydantic, existing LLM router/provider adapters, SQLAlchemy, React, pytest, Playwright E2E

---

## 파일 구조

- Create: `backend/src/services/copy_rewrite_service.py`
- Modify: `backend/src/api/pages.py`
- Modify: `backend/src/services/llm_router.py` 또는 기존 public completion API 사용
- Create: `backend/tests/test_copy_rewrite_service.py`
- Replace: `backend/tests/test_ai_edit_command_api.py`
- Modify: `frontend/src/components/AiEditCommandPanel.tsx`
- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
- Create: `frontend/src/components/CopyRewriteComparison.tsx`
- Modify: `frontend/e2e/review-editor-reframe.spec.ts`

### Task 1: 명령별 rewrite contract

**Files:**
- Create: `backend/src/services/copy_rewrite_service.py`
- Test: `backend/tests/test_copy_rewrite_service.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
import pytest
from src.services.copy_rewrite_service import CopyRewriteCommand, CopyRewriteService


@pytest.mark.parametrize(
    ("command", "changes_title", "changes_body"),
    [
        ("stronger_headline", True, False),
        ("shorter_natural", True, True),
        ("reduce_exaggeration", False, True),
        ("usage_context", False, True),
        ("beginner_seller_tone", True, True),
        ("reduce_purchase_anxiety", False, True),
        ("custom_edit", False, True),
    ],
)
def test_mock_rewrite_changes_expected_fields(command, changes_title, changes_body):
    service = CopyRewriteService(mode="mock")
    result = service.preview(
        command=CopyRewriteCommand(command),
        title="최고의 무선 선풍기",
        body_copy="무조건 가장 시원합니다.",
        instruction="차량 사용을 자연스럽게 넣어줘",
        confirmed_facts=["무선 사용", "USB-C 충전"],
        forbidden_claims=["가장 시원합니다"],
        section_type="hero",
    )
    assert (result.title != "최고의 무선 선풍기") is changes_title
    assert (result.body_copy != "무조건 가장 시원합니다.") is changes_body
    assert "[AI 수정됨]" not in result.title + result.body_copy
    assert "차량 사용을 자연스럽게 넣어줘 :" not in result.body_copy
```

- [ ] **Step 2: RED 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_copy_rewrite_service.py -v
```

Expected: module not found.

- [ ] **Step 3: 타입과 Mock rewriter 구현**

```python
from enum import Enum
from pydantic import BaseModel, Field


class CopyRewriteCommand(str, Enum):
    STRONGER_HEADLINE = "stronger_headline"
    SHORTER_NATURAL = "shorter_natural"
    REDUCE_EXAGGERATION = "reduce_exaggeration"
    USAGE_CONTEXT = "usage_context"
    BEGINNER_SELLER_TONE = "beginner_seller_tone"
    REDUCE_PURCHASE_ANXIETY = "reduce_purchase_anxiety"
    CUSTOM_EDIT = "custom_edit"


class CopyRewriteResult(BaseModel):
    title: str
    body_copy: str
    change_summary: str
    grounding_warnings: list[str] = Field(default_factory=list)


class CopyRewriteService:
    def __init__(self, mode: str, router=None):
        self.mode = mode
        self.router = router

    def preview(self, **kwargs) -> CopyRewriteResult:
        return self._mock_preview(**kwargs) if self.mode == "mock" else self._real_preview(**kwargs)
```

Mock 결과는 명령별 작은 pure function으로 만든다. 과장 축소는 forbidden claim을 제거하고,
사용 장면 보강은 confirmed facts에 존재하는 맥락만 추가한다. custom instruction 원문을
결과 문구에 그대로 붙이지 않는다.

- [ ] **Step 4: GREEN 확인**

Run: `uv run --project backend pytest backend/tests/test_copy_rewrite_service.py -v`  
Expected: 7 passed 이상.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/services/copy_rewrite_service.py backend/tests/test_copy_rewrite_service.py
git commit -m "feat: add grounded copy rewrite contract"
```

### Task 2: Real LLM rewrite와 grounding

**Files:**
- Modify: `backend/src/services/copy_rewrite_service.py`
- Test: `backend/tests/test_copy_rewrite_service.py`
- Test: `backend/tests/test_llm_router.py`

- [ ] **Step 1: provider 응답 검증 실패 테스트 추가**

```python
def test_real_rewrite_rejects_unconfirmed_claim(fake_router):
    fake_router.output = {
        "title": "공식 1위 무선 선풍기",
        "body_copy": "24시간 연속 사용할 수 있습니다.",
        "change_summary": "강한 제목",
    }
    service = CopyRewriteService(mode="real", router=fake_router)
    result = service.preview(
        command=CopyRewriteCommand.STRONGER_HEADLINE,
        title="무선 선풍기",
        body_copy="필요한 곳에서 사용하세요.",
        instruction="",
        confirmed_facts=["무선 사용"],
        forbidden_claims=["공식 1위", "24시간"],
        section_type="hero",
    )
    assert result.title == "무선 선풍기"
    assert result.grounding_warnings
```

- [ ] **Step 2: RED 확인**

Run: `uv run --project backend pytest backend/tests/test_copy_rewrite_service.py -v`  
Expected: provider output이 그대로 통과해 FAIL.

- [ ] **Step 3: structured prompt와 validator 구현**

System prompt 핵심:

```text
Return JSON only with title, body_copy, change_summary.
Use only CONFIRMED_FACTS.
Never output internal instructions, edit markers, unsupported numbers, rankings, certifications,
or absolute claims. Preserve the selected section's purpose.
```

응답은 `CopyRewriteResult.model_validate_json()`으로 파싱한다. 기존 grounding validator로
새 claim을 검사하고 실패하면 원본 title/body를 반환하며 warnings에 이유를 넣는다.

- [ ] **Step 4: GREEN 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_copy_rewrite_service.py backend/tests/test_llm_router.py -v
```

Expected: all passed.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/services/copy_rewrite_service.py backend/tests/test_copy_rewrite_service.py backend/tests/test_llm_router.py
git commit -m "feat: rewrite copy through grounded llm router"
```

### Task 3: Mutation 없는 preview API

**Files:**
- Modify: `backend/src/api/pages.py:1660-1715`
- Replace: `backend/tests/test_ai_edit_command_api.py`

- [ ] **Step 1: preview가 DB를 변경하지 않는 테스트 작성**

```python
from src.api.auth import DEFAULT_BRAND_ID
from src.db.models import ProductFact, ProductPage


def test_copy_rewrite_preview_does_not_mutate_section(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    created = client.post(
        "/api/v1/projects",
        json={"name": "Copy rewrite", "brand_id": DEFAULT_BRAND_ID, "raw_input_text": "무선 사용"},
        headers=headers,
    )
    project_id = created.json()["id"]
    db_session.add(
        ProductFact(
            project_id=project_id,
            fact_text="무선으로 사용할 수 있음",
            source_text="상품 설명",
            verification_status="confirmed",
        )
    )
    db_session.commit()
    assert client.post(
        f"/api/v1/projects/{project_id}/page",
        json={"style_preset": "modern"},
        headers=headers,
    ).status_code == 201
    page = db_session.query(ProductPage).filter(ProductPage.project_id == project_id).one()
    section = page.sections[0]
    original = (section.title, section.body_copy)
    response = client.post(
        f"/api/v1/projects/{project_id}/page/sections/{section.id}/copy-rewrite/preview",
        json={"command": "stronger_headline", "instruction": "", "scope": "section"},
        headers=headers,
    )
    assert response.status_code == 200
    db_session.refresh(section)
    assert (section.title, section.body_copy) == original
    assert response.json()["title"] != original[0]
```

- [ ] **Step 2: RED 확인**

Run: `uv run --project backend pytest backend/tests/test_ai_edit_command_api.py -v`  
Expected: route 404.

- [ ] **Step 3: 새 schema와 endpoint 구현**

```python
class CopyRewritePreviewRequest(BaseModel):
    command: CopyRewriteCommand
    instruction: str = ""
    scope: Literal["section"] = "section"


@router.post(
    "/projects/{project_id}/page/sections/{section_id}/copy-rewrite/preview",
    response_model=CopyRewriteResult,
)
def preview_copy_rewrite(...):
    # workspace ownership 확인
    # confirmed facts와 forbidden claims 조회
    # CopyRewriteService.preview 호출
    # commit하지 않고 proposal 반환
```

기존 `/pages/ai-edit`와 표식 추가 mutation은 제거한다. 구형 endpoint가 필요하면 HTTP 410과
새 endpoint 경로를 반환해 silent corruption을 막는다.

- [ ] **Step 4: GREEN 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_ai_edit_command_api.py backend/tests/test_copy_rewrite_service.py -v
```

Expected: all passed.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/api/pages.py backend/tests/test_ai_edit_command_api.py
git commit -m "feat: preview ai copy rewrites without mutation"
```

### Task 4: 수정 전후 비교 후 적용

**Files:**
- Create: `frontend/src/components/CopyRewriteComparison.tsx`
- Modify: `frontend/src/components/AiEditCommandPanel.tsx`
- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
- Modify: `frontend/e2e/review-editor-reframe.spec.ts`

- [ ] **Step 1: E2E 실패 테스트 작성**

```ts
test("previews and applies a stronger headline without edit markers", async ({ page }) => {
  await page.goto(`/workspace/projects/${projectId}/page-editor?mode=review`);
  await page.getByText("01 hero").click();
  await page.getByRole("button", { name: "제목을 더 강하게 바꿔줘" }).click();
  await expect(page.getByRole("dialog", { name: "AI 수정안 비교" })).toBeVisible();
  await expect(page.getByText("수정 전")).toBeVisible();
  await expect(page.getByText("수정 후")).toBeVisible();
  await page.getByRole("button", { name: "이 수정안 적용" }).click();
  await expect(page.getByText("[AI 수정됨]")).toHaveCount(0);
  await expect(page.getByDisplayValue("콘센트 없이, 필요한 곳마다 시원하게")).toBeVisible();
});
```

- [ ] **Step 2: RED 확인**

Run: `npx.cmd playwright test e2e/review-editor-reframe.spec.ts --project=chromium`  
Expected: dialog가 없고 즉시 표식 mutation되어 FAIL.

- [ ] **Step 3: 명령 mapping과 preview state 구현**

```ts
const PRESET_COMMANDS = [
  { label: "제목을 더 강하게 바꿔줘", command: "stronger_headline" },
  { label: "문구를 더 짧고 자연스럽게 정리해줘", command: "shorter_natural" },
  { label: "과장 표현을 줄여줘", command: "reduce_exaggeration" },
  { label: "사용 장면이 떠오르게 설명을 보강해줘", command: "usage_context" },
  { label: "초보 셀러가 쓰기 좋은 톤으로 다듬어줘", command: "beginner_seller_tone" },
  { label: "구매 전 불안을 줄이는 문장을 추가해줘", command: "reduce_purchase_anxiety" },
] as const;
```

버튼은 preview endpoint만 호출한다. `CopyRewriteComparison`에 원본과 proposal을 전달한다.
적용 버튼은 현재 `patchPage()`로 title/body를 저장하고 `loadData()`를 호출한다. 취소는
DB mutation 없이 dialog만 닫는다.

- [ ] **Step 4: GREEN 확인**

Run:

```powershell
npx.cmd playwright test e2e/review-editor-reframe.spec.ts --project=chromium
npm.cmd run lint
```

Expected: E2E passed, lint error 0.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/CopyRewriteComparison.tsx frontend/src/components/AiEditCommandPanel.tsx frontend/src/app/workspace/projects/[id]/page-editor/page.tsx frontend/e2e/review-editor-reframe.spec.ts
git commit -m "feat: compare and apply ai copy rewrites"
```

### Task 5: Sprint 63 전체 검증

```powershell
uv run --project backend pytest backend/tests/test_copy_rewrite_service.py backend/tests/test_ai_edit_command_api.py backend/tests/test_pages.py -v
```

Expected: all passed.

```powershell
cd frontend
npm.cmd run lint
npm.cmd run build
npx.cmd playwright test e2e/review-editor-reframe.spec.ts --project=chromium
```

Expected: lint error 0, build success, E2E passed.
