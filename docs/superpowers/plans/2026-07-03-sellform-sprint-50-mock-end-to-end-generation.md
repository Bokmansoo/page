# Sellform Sprint 50 Mock End-To-End Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** API 크레딧을 전혀 쓰지 않고 mock mode에서 상품 입력부터 완성형 상세페이지 초안까지 한 번에 생성한다.

**Architecture:** Sprint 48의 `AgentGraph`를 확장해 모든 생성 단계를 deterministic mock output으로 채운다. Sprint 45의 상세페이지 패키지/렌더링 기반을 재사용하되, 빈 placeholder가 아니라 mock copy와 mock visual assets가 들어간 페이지를 만든다. mock 결과 화면은 어두운 편집기 프레임이 아니라, 흰 배경의 완성형 상세페이지 초안처럼 먼저 보여야 한다.

**Tech Stack:** FastAPI, Pydantic, pytest, existing page/package services, Next.js.

---

## File Structure

- Modify: `backend/src/agents/graph.py`
- Create: `backend/src/agents/mock_outputs.py`
- Create: `backend/src/services/agent_run_service.py`
- Modify: `backend/src/api/agent_runs.py`
- Test: `backend/tests/test_mock_agent_generation.py`
- Test: `backend/tests/test_agent_run_api.py`
- Modify: `frontend/src/components/GenerationProgressShell.tsx`
- Create: `frontend/e2e/mock-generation.spec.ts`

## Tasks

### Task 1: Mock output fixtures 정의

**Files:**
- Create: `backend/src/agents/mock_outputs.py`
- Test: `backend/tests/test_mock_agent_generation.py`

- [ ] **Step 1: Write failing test**

```python
from backend.src.agents.mock_outputs import build_mock_product_understanding, build_mock_page_assembly


def test_mock_product_understanding_uses_input_name():
    result = build_mock_product_understanding(product_name="유아 자전거")
    assert result["product_type"] == "유아 자전거"
    assert "target_customer" in result
    assert result["verified_facts"]


def test_mock_page_assembly_has_copy_and_visual_slots():
    result = build_mock_page_assembly(product_name="유아 자전거")
    assert len(result["sections"]) >= 5
    assert all(section["title"] for section in result["sections"])
    assert all(section["visual_role"] for section in result["sections"])
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && uv run pytest tests/test_mock_agent_generation.py -v`  
Expected: FAIL because mock output module does not exist.

- [ ] **Step 3: Implement mock builders**

Create deterministic builders for:

- `product_understanding`
- `sales_strategy`
- `page_plan`
- `copy_set`
- `visual_plan`
- `generated_assets`
- `page_assembly`
- `qa_report`

Use Korean copy and placeholder asset IDs such as `mock-hero-visual`.

- [ ] **Step 4: Run test**

Run: `cd backend && uv run pytest tests/test_mock_agent_generation.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/agents/mock_outputs.py backend/tests/test_mock_agent_generation.py
git commit -m "feat: add mock generation outputs"
```

### Task 2: AgentGraph 전체 mock run 구현

**Files:**
- Modify: `backend/src/agents/graph.py`
- Test: `backend/tests/test_mock_agent_generation.py`

- [ ] **Step 1: Add failing test**

```python
from backend.src.agents.graph import AgentGraph
from backend.src.agents.state import AgentRunState, AgentStage, ProductInput


def test_mock_graph_runs_to_review_editor():
    graph = AgentGraph.mock()
    state = AgentRunState(project_id="p1", product_input=ProductInput(product_name="유아 자전거"))
    completed = graph.run_all(state)
    assert completed.current_stage == AgentStage.REVIEW_EDITOR
    assert "product_understanding" in completed.outputs
    assert "sales_strategy" in completed.outputs
    assert "page_assembly" in completed.outputs
    assert completed.outputs["page_assembly"]["sections"]
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && uv run pytest tests/test_mock_agent_generation.py::test_mock_graph_runs_to_review_editor -v`  
Expected: FAIL because `run_all` is missing or incomplete.

- [ ] **Step 3: Implement `run_all`**

`run_all` must advance through all non-user-blocking mock stages and stop at `review_editor`. It must not call external APIs.

- [ ] **Step 4: Run test**

Run: `cd backend && uv run pytest tests/test_mock_agent_generation.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/agents/graph.py backend/tests/test_mock_agent_generation.py
git commit -m "feat: run mock agent pipeline end to end"
```

### Task 3: Agent run service와 API 연결

**Files:**
- Create: `backend/src/services/agent_run_service.py`
- Modify: `backend/src/api/agent_runs.py`
- Test: `backend/tests/test_agent_run_api.py`

- [ ] **Step 1: Add API test**

```python
def test_run_mock_generation_returns_page_assembly(client, auth_headers):
    created = client.post(
        "/api/agent-runs",
        headers=auth_headers,
        json={"product_name": "유아 자전거"},
    ).json()
    response = client.post(f"/api/agent-runs/{created['id']}/run-mock", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["current_stage"] == "review_editor"
    assert data["outputs"]["page_assembly"]["sections"]
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && uv run pytest tests/test_agent_run_api.py -v`  
Expected: FAIL because `/run-mock` endpoint does not exist.

- [ ] **Step 3: Implement service and endpoint**

`AgentRunService.run_mock(run_id)` loads the current state, calls `AgentGraph.mock().run_all`, persists outputs, and returns the updated state.

- [ ] **Step 4: Run test**

Run: `cd backend && uv run pytest tests/test_agent_run_api.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/agent_run_service.py backend/src/api/agent_runs.py backend/tests/test_agent_run_api.py
git commit -m "feat: expose mock generation run api"
```

### Task 4: Frontend progress and result 연결

**Files:**
- Modify: `frontend/src/components/GenerationProgressShell.tsx`
- Create: `frontend/e2e/mock-generation.spec.ts`

- [ ] **Step 1: Update progress shell**

After intake creation, call `/api/agent-runs/{id}/run-mock` in mock mode and show completed steps. On success, show CTA `생성된 상세페이지 보기`.

The completed state should keep the same visual direction as the start screen:

- white or near-white background
- soft mint/green success state
- clear preview CTA
- no dominant dark navy sidebar
- no editor controls before the generated page draft exists

- [ ] **Step 2: Add E2E test**

```ts
import { test, expect } from "@playwright/test";

test("mock mode creates a complete detail page draft", async ({ page }) => {
  await page.goto("/workspace");
  await page.getByPlaceholder("상품명").fill("유아 자전거");
  await page.getByRole("button", { name: "AI 상세페이지 만들기" }).click();
  await expect(page.getByText("상세페이지 조립")).toBeVisible();
  await expect(page.getByRole("button", { name: "생성된 상세페이지 보기" })).toBeVisible();
});
```

- [ ] **Step 3: Run E2E**

Run: `cd frontend && npm.cmd test -- --grep "mock mode creates"`  
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/GenerationProgressShell.tsx frontend/e2e/mock-generation.spec.ts
git commit -m "feat: connect mock generation UI"
```

## Done Criteria

- Mock completion follows `DESIGN.md`: white-first surface, calm green/mint progress and success states, and generated detail page preview as the primary object.
- Mock result copy uses seller-friendly language and avoids customer-facing raw terms like prompt, provider, agent node, or workflow unless shown in diagnostics.
- Mock image slots clearly label source type: uploaded, URL-extracted, mock-generated, or pending real generation.
- One click can create a full mock detail page draft.
- The flow produces product understanding, sales strategy, copy, visual plan, placeholder images, page assembly, and QA report.
- No external LLM/image API is called.
- Mock completion feels like an AI 생성 결과 화면, not a dark admin/editor workspace.
- Backend and E2E tests pass.
