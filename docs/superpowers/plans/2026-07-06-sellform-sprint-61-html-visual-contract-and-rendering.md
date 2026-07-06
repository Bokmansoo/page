# Sellform Sprint 61 HTML Visual Contract and Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 이미지 섹션과 HTML 그래픽 섹션을 DB부터 결과 화면까지 보존하고 빈 placeholder를 실제 상세페이지 시각 요소로 교체한다.

**Architecture:** `PageSection`에 `visual_kind`와 `visual_payload`를 추가하고 `page_visual_contract.py`가 정규화와 유효성 검사를 전담한다. 프론트는 `DetailPageDocument`에서 visual kind/layout별 작은 renderer를 선택한다.

**Tech Stack:** FastAPI, SQLAlchemy JSON, Pydantic, Next.js, React, Tailwind CSS, pytest, Playwright E2E

---

## 파일 구조

- Create: `backend/src/services/page_visual_contract.py` — visual payload 정규화/유효성
- Modify: `backend/src/db/models.py` — `PageSection` 컬럼
- Modify: `backend/src/db/database.py` — 기존 DB compatibility DDL
- Modify: `backend/src/services/agent_run_service.py` — assembly output 저장
- Modify: `backend/src/api/pages.py` — request/response/snapshot round trip
- Modify: `backend/src/agents/nodes/page_assembly/agent.py` — canonical payload 생성
- Create: `backend/tests/test_page_visual_contract.py`
- Create: `frontend/src/components/detail-page/types.ts`
- Create: `frontend/src/components/detail-page/ImageSectionVisual.tsx`
- Create: `frontend/src/components/detail-page/HtmlGraphicVisual.tsx`
- Modify: `frontend/src/components/DetailPageDocument.tsx`
- Modify: `frontend/src/components/GeneratedDetailPageResult.tsx`
- Create: `frontend/e2e/upload-ready-detail-page.spec.ts`

### Task 1: Visual contract 정의

**Files:**
- Create: `backend/src/services/page_visual_contract.py`
- Test: `backend/tests/test_page_visual_contract.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from src.services.page_visual_contract import normalize_visual, validate_visual


def test_html_graphic_is_complete_without_image_asset():
    visual = normalize_visual(
        section_type="comparison",
        image_asset_id=None,
        visual_kind="html_graphic",
        visual_payload={
            "layout_variant": "comparison_cards",
            "cards": [
                {"title": "기존 방식", "body": "전원 위치에 제약", "tone": "muted"},
                {"title": "무선 사용", "body": "필요한 장소로 이동", "tone": "positive"},
            ],
        },
    )
    assert validate_visual(visual) == []


def test_image_visual_requires_asset_id():
    visual = normalize_visual(
        section_type="hero",
        image_asset_id=None,
        visual_kind="image",
        visual_payload={"layout_variant": "hero_overlay"},
    )
    assert validate_visual(visual) == ["image_asset_required"]
```

- [ ] **Step 2: RED 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_page_visual_contract.py -v
```

Expected: FAIL with `ModuleNotFoundError: src.services.page_visual_contract`.

- [ ] **Step 3: 최소 contract 구현**

```python
from typing import Any

VISUAL_KINDS = {"image", "html_graphic"}
HTML_LAYOUTS = {"comparison_cards", "benefit_cards", "spec_table"}


def normalize_visual(
    *,
    section_type: str,
    image_asset_id: str | None,
    visual_kind: str | None,
    visual_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    kind = visual_kind or ("image" if image_asset_id else "html_graphic")
    payload = dict(visual_payload or {})
    payload.setdefault(
        "layout_variant",
        {
            "comparison": "comparison_cards",
            "detail_1": "benefit_cards",
            "guarantee": "spec_table",
        }.get(section_type, "image_text"),
    )
    return {
        "visual_kind": kind,
        "visual_payload": payload,
        "image_asset_id": image_asset_id,
    }


def validate_visual(visual: dict[str, Any]) -> list[str]:
    kind = visual["visual_kind"]
    payload = visual["visual_payload"]
    if kind not in VISUAL_KINDS:
        return ["invalid_visual_kind"]
    if kind == "image" and not visual.get("image_asset_id"):
        return ["image_asset_required"]
    if kind == "html_graphic":
        layout = payload.get("layout_variant")
        if layout not in HTML_LAYOUTS:
            return ["invalid_html_layout"]
        if layout in {"comparison_cards", "benefit_cards"} and not payload.get("cards"):
            return ["html_cards_required"]
        if layout == "spec_table" and not payload.get("table_rows"):
            return ["spec_rows_required"]
    return []
```

- [ ] **Step 4: GREEN 확인**

Run: `uv run --project backend pytest backend/tests/test_page_visual_contract.py -v`  
Expected: 2 passed.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/services/page_visual_contract.py backend/tests/test_page_visual_contract.py
git commit -m "feat: define canonical page visual contract"
```

### Task 2: DB와 API round trip

**Files:**
- Modify: `backend/src/db/models.py:213`
- Modify: `backend/src/db/database.py:20`
- Modify: `backend/src/api/pages.py:49-104`
- Test: `backend/tests/test_page_visual_contract.py`

- [ ] **Step 1: API round-trip 실패 테스트 추가**

```python
from src.api.auth import DEFAULT_BRAND_ID
from src.db.models import ProductPage


def test_page_api_returns_html_visual_payload(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    created = client.post(
        "/api/v1/projects",
        json={"name": "Visual contract", "brand_id": DEFAULT_BRAND_ID, "raw_input_text": "무선 사용"},
        headers=headers,
    )
    project_id = created.json()["id"]
    assert client.post(
        f"/api/v1/projects/{project_id}/page",
        json={"style_preset": "modern"},
        headers=headers,
    ).status_code == 201
    page = db_session.query(ProductPage).filter(ProductPage.project_id == project_id).one()
    section = page.sections[0]
    section.visual_kind = "html_graphic"
    section.visual_payload = {
        "layout_variant": "benefit_cards",
        "cards": [{"title": "간편한 이동", "body": "필요한 곳으로 옮겨 사용"}],
    }
    section.image_asset_id = None
    db_session.commit()

    response = client.get(
        f"/api/v1/projects/{project_id}/page",
        headers=headers,
    )
    assert response.status_code == 200
    item = response.json()["sections"][0]
    assert item["visual_kind"] == "html_graphic"
    assert item["visual_payload"]["layout_variant"] == "benefit_cards"
```

- [ ] **Step 2: RED 확인**

Run: `uv run --project backend pytest backend/tests/test_page_visual_contract.py -v`  
Expected: response에 `visual_kind`가 없어 FAIL.

- [ ] **Step 3: 모델과 compatibility DDL 추가**

`backend/src/db/models.py`:

```python
visual_kind = Column(String(30), nullable=True)
visual_payload = Column(JSON, nullable=True)
```

`backend/src/db/database.py`:

```python
if "page_sections" in table_names:
    existing = {column["name"] for column in inspector.get_columns("page_sections")}
    with engine.begin() as connection:
        if "visual_kind" not in existing:
            connection.execute(text("ALTER TABLE page_sections ADD COLUMN visual_kind VARCHAR(30)"))
        if "visual_payload" not in existing:
            connection.execute(text("ALTER TABLE page_sections ADD COLUMN visual_payload JSON"))
```

- [ ] **Step 4: Pydantic schema와 response builder 연결**

`SectionUpdateSchema`, `SectionCreateSchema`, `SectionResponseSchema`에 추가:

```python
visual_kind: Optional[Literal["image", "html_graphic"]] = None
visual_payload: Optional[dict] = None
```

`build_section_response()`에 추가:

```python
visual_kind=section.visual_kind or ("image" if section.image_asset_id else None),
visual_payload=section.visual_payload or {},
```

`save_page_details()`는 전달된 두 필드를 저장하되 `validate_visual()` 오류가 있으면
HTTP 422와 `{section_id, issues}`를 반환한다.

- [ ] **Step 5: GREEN 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_page_visual_contract.py backend/tests/test_pages.py backend/tests/test_runtime_schema_compatibility.py -v
```

Expected: all passed.

- [ ] **Step 6: Commit**

```powershell
git add backend/src/db/models.py backend/src/db/database.py backend/src/api/pages.py backend/tests/test_page_visual_contract.py
git commit -m "feat: persist section visual contract"
```

### Task 3: Agent assembly와 version snapshot 보존

**Files:**
- Modify: `backend/src/agents/nodes/page_assembly/agent.py:51-100`
- Modify: `backend/src/services/agent_run_service.py:125-180`
- Modify: `backend/src/api/pages.py` (`create_page_snapshot`)
- Test: `backend/tests/test_page_assembly_with_generated_assets.py`
- Test: `backend/tests/test_page_version_service.py`

- [ ] **Step 1: HTML graphic persistence 실패 테스트 작성**

```python
from src.agents.nodes.page_assembly.agent import PageAssemblyAgent
from src.agents.state import AgentRunState


def test_assembly_preserves_html_graphic_payload():
    state = AgentRunState(
        project_id="project-1",
        outputs={
            "visual_planning": {
                "scene_plan": {
                    "sections": [
                        {
                            "section_id": "pain_points",
                            "target_slot_id": "comparison",
                            "visual_strategy": "html_graphic",
                            "visual_payload": {
                                "layout_variant": "comparison_cards",
                                "cards": [{"title": "이동", "body": "필요한 곳에서 사용"}],
                            },
                        }
                    ]
                }
            },
            "image_generation": {"candidates": {}},
        },
    )
    output = PageAssemblyAgent().run(state).outputs["page_assembly"]
    comparison = next(item for item in output["sections"] if item["id"] == "sec-2")
    assert comparison["visual_kind"] == "html_graphic"
    assert comparison["visual_payload"]["cards"][0]["title"] == "이동"
    assert comparison["image_asset_id"] is None
```

- [ ] **Step 2: RED 확인**

Run: `uv run --project backend pytest backend/tests/test_page_assembly_with_generated_assets.py -v`  
Expected: stored section에 visual fields가 없어 FAIL.

- [ ] **Step 3: 저장 경로 수정**

`page_assembly`의 HTML 분기:

```python
section["visual_kind"] = "html_graphic"
section["visual_payload"] = scene.get("visual_payload") or {
    "layout_variant": {
        "comparison": "comparison_cards",
        "detail_1": "benefit_cards",
        "guarantee": "spec_table",
    }[slot_id]
}
section["image_asset_id"] = None
```

`agent_run_service`의 `PageSection(...)`:

```python
visual_kind=section.get("visual_kind"),
visual_payload=section.get("visual_payload") or {},
```

`create_page_snapshot()`에도 동일 필드를 포함한다.

- [ ] **Step 4: GREEN 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_page_assembly_with_generated_assets.py backend/tests/test_page_version_service.py -v
```

Expected: all passed.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/agents/nodes/page_assembly/agent.py backend/src/services/agent_run_service.py backend/src/api/pages.py backend/tests/test_page_assembly_with_generated_assets.py backend/tests/test_page_version_service.py
git commit -m "feat: preserve html visuals through assembly"
```

### Task 4: Canonical React renderer

**Files:**
- Create: `frontend/src/components/detail-page/types.ts`
- Create: `frontend/src/components/detail-page/ImageSectionVisual.tsx`
- Create: `frontend/src/components/detail-page/HtmlGraphicVisual.tsx`
- Modify: `frontend/src/components/DetailPageDocument.tsx`
- Modify: `frontend/src/components/GeneratedDetailPageResult.tsx`
- Test: `frontend/e2e/upload-ready-detail-page.spec.ts`

- [ ] **Step 1: E2E 실패 fixture 작성**

API fixture는 5개 섹션을 반환한다:

```ts
const sections = [
  { section_type: "hero", visual_kind: "image", image_asset_id: "hero", visual_payload: { layout_variant: "hero_overlay" } },
  { section_type: "comparison", visual_kind: "html_graphic", image_asset_id: null, visual_payload: { layout_variant: "comparison_cards", cards: [{ title: "유선", body: "위치 제약" }, { title: "무선", body: "간편한 이동" }] } },
  { section_type: "detail_1", visual_kind: "html_graphic", image_asset_id: null, visual_payload: { layout_variant: "benefit_cards", cards: [{ title: "필요한 순간", body: "바로 사용" }] } },
  { section_type: "detail_2", visual_kind: "image", image_asset_id: "lifestyle", visual_payload: { layout_variant: "image_text" } },
  { section_type: "guarantee", visual_kind: "html_graphic", image_asset_id: null, visual_payload: { layout_variant: "spec_table", table_rows: [{ label: "충전 방식", value: "판매자 확인", verification_status: "needs_review" }] } },
];
```

Assertions:

```ts
await expect(page.getByText("간편한 이동")).toBeVisible();
await expect(page.getByText("충전 방식")).toBeVisible();
await expect(page.getByText("이미지 확인이 필요합니다")).toHaveCount(0);
await expect(page.getByRole("button", { name: /PNG/ })).toBeEnabled();
```

- [ ] **Step 2: RED 확인**

Run:

```powershell
npx.cmd playwright test e2e/upload-ready-detail-page.spec.ts --project=chromium
```

Expected: HTML 카드가 없고 다운로드 버튼이 disabled라 FAIL.

- [ ] **Step 3: 공통 타입 추가**

```ts
export type VisualKind = "image" | "html_graphic";

export interface VisualCard {
  icon_key?: string;
  title: string;
  body: string;
  tone?: "positive" | "muted" | "warning";
}

export interface VisualPayload {
  layout_variant: "hero_overlay" | "image_text" | "comparison_cards" | "benefit_cards" | "spec_table";
  eyebrow?: string;
  badges?: string[];
  cards?: VisualCard[];
  table_rows?: Array<{ label: string; value: string; verification_status?: string }>;
  palette?: { surface?: string; accent?: string; text?: string };
}
```

- [ ] **Step 4: 작은 renderer 구현**

`HtmlGraphicVisual`은 `layout_variant`를 switch해 cards/table을 렌더링한다. 모든 wrapper에
`data-section-visual="html_graphic"`을 부여한다.

`ImageSectionVisual`은 image, scrim, section title/body/badges를 DOM overlay로 렌더링하고
`data-section-visual="image"`를 부여한다.

`DetailPageDocument`:

```tsx
const visual = section.visual_kind === "html_graphic"
  ? <HtmlGraphicVisual section={section} />
  : <ImageSectionVisual section={section} asset={matchedAsset} exportMode={exportMode} />;
```

- [ ] **Step 5: 누락 계산 수정**

`GeneratedDetailPageResult`:

```ts
const invalidVisualCount = visibleSections.filter(
  (section) => validateSectionVisual(section).length > 0
).length;
```

`image_asset_id`만 보는 `missingVisualCount`를 제거한다.

- [ ] **Step 6: GREEN 확인**

Run:

```powershell
npx.cmd playwright test e2e/upload-ready-detail-page.spec.ts --project=chromium
npm.cmd run lint
```

Expected: E2E passed, lint error 0.

- [ ] **Step 7: Commit**

```powershell
git add frontend/src/components/detail-page frontend/src/components/DetailPageDocument.tsx frontend/src/components/GeneratedDetailPageResult.tsx frontend/e2e/upload-ready-detail-page.spec.ts
git commit -m "feat: render image overlays and html graphics"
```

### Task 5: Sprint 61 전체 검증

- [ ] **Step 1: Backend regression**

```powershell
uv run --project backend pytest backend/tests/test_page_visual_contract.py backend/tests/test_page_assembly_with_generated_assets.py backend/tests/test_pages.py backend/tests/test_page_version_service.py -v
```

Expected: all passed.

- [ ] **Step 2: Frontend production build**

```powershell
cd frontend
npm.cmd run build
```

Expected: production build 성공, result/render route 포함.

- [ ] **Step 3: Chromium E2E**

```powershell
npx.cmd playwright test e2e/upload-ready-detail-page.spec.ts --project=chromium
```

Expected: 1 passed 이상.
