# Sellform Sprint 55 Source Reference And Candidate Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사진/URL 입력을 11-Agent 구조 안에서 안정적으로 수집하고, URL 상세페이지를 참고 분석하며, 상세페이지 이미지 후보를 사용자가 선택할 수 있는 계약을 완성한다.

**Architecture:** Sprint 54가 11개 노드의 구조를 만든 뒤, Sprint 55는 `source_collection`, `reference_analysis`, `image_generation`, `page_assembly` 사이의 데이터 계약을 강화한다. 이 sprint는 실제 고비용 이미지 생성을 필수로 하지 않고, 업로드 이미지와 URL 추출 이미지, mock-generated 후보를 일관되게 보여주는 데 집중한다.

**Tech Stack:** FastAPI, SQLAlchemy, existing asset API, pytest, Next.js, Playwright.

---

## File Structure

- Modify: `backend/src/agents/nodes/source_collection/agent.py`
- Modify: `backend/src/agents/nodes/source_collection/schema.py`
- Modify: `backend/src/agents/nodes/reference_analysis/agent.py`
- Modify: `backend/src/agents/nodes/reference_analysis/schema.py`
- Modify: `backend/src/agents/nodes/image_generation/agent.py`
- Modify: `backend/src/agents/nodes/image_generation/schema.py`
- Modify: `backend/src/agents/nodes/page_assembly/agent.py`
- Modify: `backend/src/agents/state.py`
- Modify: `backend/src/api/pages.py`
- Modify: `backend/src/api/files.py`
- Create: `backend/tests/test_source_collection_agent.py`
- Create: `backend/tests/test_reference_analysis_agent.py`
- Create: `backend/tests/test_image_candidate_selection_contract.py`
- Modify: `frontend/src/components/GeneratedDetailPageResult.tsx`
- Modify: `frontend/src/components/ReviewEditorLayout.tsx`
- Create: `frontend/e2e/image-candidate-selection.spec.ts`

## Tasks

### Task 1: Source Collection Agent가 업로드/URL 소스를 구조화

**Files:**
- Modify: `backend/src/agents/nodes/source_collection/agent.py`
- Modify: `backend/src/agents/nodes/source_collection/schema.py`
- Test: `backend/tests/test_source_collection_agent.py`

- [ ] **Step 1: Write failing source collection test**

```python
from backend.src.agents.nodes.source_collection.agent import SourceCollectionAgent
from backend.src.agents.state import AgentRunState


def test_source_collection_preserves_uploaded_and_url_sources():
    state = AgentRunState(
        project_id="project-1",
        input_snapshot={
            "product_name": "삼성 삼탠바이미 32인치 스마트모니터",
            "product_url": "https://example.com/product",
            "uploaded_assets": [
                {"asset_id": "asset-1", "filename": "삼탠바이미.png", "mime_type": "image/png"}
            ],
        },
    )

    result = SourceCollectionAgent().run(state)
    sources = result.outputs["source_collection"]

    assert sources["product_url"] == "https://example.com/product"
    assert sources["uploaded_images"][0]["asset_id"] == "asset-1"
    assert sources["uploaded_images"][0]["source_type"] == "uploaded"
    assert sources["source_summary"]["has_uploaded_image"] is True
    assert sources["source_summary"]["has_product_url"] is True
```

- [ ] **Step 2: Run test and verify failure**

Run: `cd backend && uv run pytest tests/test_source_collection_agent.py -v`  
Expected: FAIL until the agent returns structured sources.

- [ ] **Step 3: Implement source schema and agent**

`SourceCollectionAgent` must output:

```python
{
    "product_url": "...",
    "uploaded_images": [
        {"asset_id": "...", "filename": "...", "source_type": "uploaded"}
    ],
    "url_images": [],
    "reference_text_blocks": [],
    "source_summary": {
        "has_uploaded_image": True,
        "has_product_url": True,
        "primary_visual_source": "uploaded",
    },
}
```

- [ ] **Step 4: Run test and verify pass**

Run: `cd backend && uv run pytest tests/test_source_collection_agent.py -v`  
Expected: PASS.

### Task 2: Reference Analysis Agent가 URL 참고를 복제 위험 없이 분석

**Files:**
- Modify: `backend/src/agents/nodes/reference_analysis/agent.py`
- Modify: `backend/src/agents/nodes/reference_analysis/schema.py`
- Test: `backend/tests/test_reference_analysis_agent.py`

- [ ] **Step 1: Write failing reference analysis test**

```python
from backend.src.agents.nodes.reference_analysis.agent import ReferenceAnalysisAgent
from backend.src.agents.state import AgentRunState


def test_reference_analysis_extracts_takeaways_without_copying():
    state = AgentRunState(
        project_id="project-1",
        outputs={
            "source_collection": {
                "product_url": "https://example.com/product",
                "reference_text_blocks": [
                    "우리 아이 첫 자전거, 아직도 망설이고 계세요?",
                    "아이 먼저 찾는 자전거",
                ],
            }
        },
    )

    result = ReferenceAnalysisAgent().run(state)
    analysis = result.outputs["reference_analysis"]

    assert analysis["reference_available"] is True
    assert analysis["structure_takeaways"]
    assert analysis["copy_risk_notes"]
    assert "우리 아이 첫 자전거, 아직도 망설이고 계세요?" not in analysis["recommended_rewrite_direction"]
```

- [ ] **Step 2: Run test and verify failure**

Run: `cd backend && uv run pytest tests/test_reference_analysis_agent.py -v`  
Expected: FAIL until analysis output exists.

- [ ] **Step 3: Implement deterministic reference analysis**

In mock mode, analyze structure only:

```python
{
    "reference_available": True,
    "structure_takeaways": ["문제 제기형 히어로", "사용 장면 중심 보강", "구매 전 걱정 해소"],
    "visual_takeaways": ["상단 대표컷", "중간 사용 장면", "하단 FAQ"],
    "copy_risk_notes": ["원문 제목 직접 복제 금지", "문장 구조를 새로 작성"],
    "recommended_rewrite_direction": "참고 페이지의 설득 흐름만 사용하고 문구와 섹션명은 새로 만든다.",
}
```

- [ ] **Step 4: Run test and verify pass**

Run: `cd backend && uv run pytest tests/test_reference_analysis_agent.py -v`  
Expected: PASS.

### Task 3: 이미지 후보 선택 계약 추가

**Files:**
- Modify: `backend/src/agents/nodes/image_generation/schema.py`
- Modify: `backend/src/agents/nodes/image_generation/agent.py`
- Modify: `backend/src/agents/state.py`
- Test: `backend/tests/test_image_candidate_selection_contract.py`

- [ ] **Step 1: Write failing candidate contract test**

```python
from backend.src.agents.nodes.image_generation.agent import ImageGenerationAgent
from backend.src.agents.state import AgentRunState


def test_image_generation_returns_candidates_per_visual_slot():
    state = AgentRunState(
        project_id="project-1",
        outputs={
            "source_collection": {
                "uploaded_images": [
                    {"asset_id": "asset-1", "filename": "삼탠바이미.png", "source_type": "uploaded"}
                ],
                "url_images": [],
            },
            "visual_planning": {
                "visual_slots": [
                    {"slot_id": "hero", "role": "대표 상품 컷"},
                    {"slot_id": "usage", "role": "사용 장면 컷"},
                ]
            },
        },
    )

    result = ImageGenerationAgent().run(state)
    candidates = result.outputs["image_generation"]["candidates"]

    assert candidates["hero"][0]["source_type"] == "uploaded"
    assert candidates["hero"][0]["asset_id"] == "asset-1"
    assert candidates["usage"][0]["source_type"] in {"uploaded", "mock-generated"}
```

- [ ] **Step 2: Run test and verify failure**

Run: `cd backend && uv run pytest tests/test_image_candidate_selection_contract.py -v`  
Expected: FAIL until candidates are produced.

- [ ] **Step 3: Implement candidate output**

Each candidate must include:

```python
{
    "candidate_id": "hero-uploaded-asset-1",
    "slot_id": "hero",
    "asset_id": "asset-1",
    "source_type": "uploaded",
    "label": "업로드 이미지",
    "is_recommended": True,
    "needs_identity_review": False,
}
```

- [ ] **Step 4: Run test and verify pass**

Run: `cd backend && uv run pytest tests/test_image_candidate_selection_contract.py -v`  
Expected: PASS.

### Task 4: Page Assembly가 선택 후보를 반영

**Files:**
- Modify: `backend/src/agents/nodes/page_assembly/agent.py`
- Test: `backend/tests/test_image_candidate_selection_contract.py`

- [ ] **Step 1: Add failing selected-candidate test**

```python
from backend.src.agents.nodes.page_assembly.agent import PageAssemblyAgent
from backend.src.agents.state import AgentRunState


def test_page_assembly_uses_selected_image_candidate():
    state = AgentRunState(
        project_id="project-1",
        selected_image_candidates={"hero": "candidate-hero-selected"},
        outputs={
            "page_planning": {"sections": [{"section_id": "hero", "role": "hero"}]},
            "copywriting": {"sections": {"hero": {"title": "공간을 바꾸는 스마트 모니터"}}},
            "image_generation": {
                "candidates": {
                    "hero": [
                        {"candidate_id": "candidate-hero-default", "asset_id": "asset-default", "source_type": "mock-generated"},
                        {"candidate_id": "candidate-hero-selected", "asset_id": "asset-selected", "source_type": "uploaded"},
                    ]
                }
            },
        },
    )

    result = PageAssemblyAgent().run(state)
    hero = result.outputs["page_assembly"]["sections"][0]
    assert hero["visual_slot"]["asset_id"] == "asset-selected"
```

- [ ] **Step 2: Run test and verify failure**

Run: `cd backend && uv run pytest tests/test_image_candidate_selection_contract.py::test_page_assembly_uses_selected_image_candidate -v`  
Expected: FAIL until selected candidates are used.

- [ ] **Step 3: Implement selected candidate mapping**

`PageAssemblyAgent` must prefer `state.selected_image_candidates[slot_id]`. If none exists, use the first `is_recommended` candidate. If no candidate exists, set `visual_slot.status = "missing_image"`.

- [ ] **Step 4: Run backend tests**

Run: `cd backend && uv run pytest tests/test_source_collection_agent.py tests/test_reference_analysis_agent.py tests/test_image_candidate_selection_contract.py -v`  
Expected: PASS.

### Task 5: Frontend 후보 선택 UI 연결

**Files:**
- Modify: `frontend/src/components/GeneratedDetailPageResult.tsx`
- Modify: `frontend/src/components/ReviewEditorLayout.tsx`
- Create: `frontend/e2e/image-candidate-selection.spec.ts`

- [ ] **Step 1: Add E2E test**

```ts
import { test, expect } from "@playwright/test";

test("seller can see and select image candidates", async ({ page }) => {
  await page.goto("/workspace");
  await page.getByLabel("상품명").fill("삼성 삼탠바이미 32인치 스마트모니터");
  await page.getByRole("button", { name: "AI 상세페이지 만들기" }).click();
  await page.getByRole("button", { name: "생성된 상세페이지 보기" }).click();

  await expect(page.getByText("이미지 후보")).toBeVisible();
  await expect(page.getByText("업로드 이미지").or(page.getByText("목업 이미지"))).toBeVisible();
});
```

- [ ] **Step 2: Run E2E and verify failure**

Run: `cd frontend && npm.cmd test -- --grep "image candidates"`  
Expected: FAIL until candidate UI exists.

- [ ] **Step 3: Render candidate cards**

Result/review screens should show candidate cards per section with:

- source label: `업로드 이미지`, `URL 추출 이미지`, `목업 이미지`, `생성 이미지`
- selected state
- warning state if identity review is required
- button label: `이 이미지 사용`

- [ ] **Step 4: Run E2E**

Run: `cd frontend && npm.cmd test -- --grep "image candidates"`  
Expected: PASS.

## Done Criteria

- 업로드 이미지와 URL 소스가 구조화되어 `source_collection`에 저장된다.
- URL 상세페이지는 참고 분석되지만 원문 문구를 그대로 복제하지 않는다.
- 이미지 후보는 visual slot 단위로 생성된다.
- 사용자가 선택한 이미지 후보가 `page_assembly`에 반영된다.
- 결과/검수 화면에서 이미지 후보와 출처를 볼 수 있다.
- Mock mode는 외부 API를 호출하지 않는다.

