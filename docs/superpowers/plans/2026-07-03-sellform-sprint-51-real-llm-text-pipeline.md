# Sellform Sprint 51 Real LLM Text Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 상품 이해, 판매 전략, 상세페이지 구조, 카피 생성을 실제 LLM provider로 연결하되 이미지 생성은 아직 mock으로 유지한다.

**Architecture:** Sprint 48의 provider adapter 계약을 구현한다. Primary는 OpenAI GPT 계열, fallback 후보는 Gemini 2.5 Flash와 Claude 계열로 둔다. 모든 응답은 schema validation을 거쳐 agent state에 저장한다.

**Tech Stack:** FastAPI, existing `llm_router`, Pydantic schemas, pytest with mocked providers.

---

## DESIGN.md Alignment

Sprint 51 connects real text generation, so the LLM output must serve the product experience defined in `DESIGN.md`.

Text generation should make Sellform feel like a practical detail page production service for solo sellers, not a visible AI prompt tool.

Required output behavior:

- Generated customer-facing copy must be clear Korean commerce copy.
- The LLM should produce detail page script, section titles, selling points, image direction, and QA notes that can be rendered in a white-first soft commerce UI.
- User-facing output should not expose raw provider/model details.
- Internal trace may store provider, cost, fallback, and prompt metadata, but the main result screen should show seller-friendly labels.
- The pipeline must support the `DESIGN.md` flow: product input -> AI generation pipeline -> complete detail page draft -> review editor.

Done Criteria addition:

- Real LLM text output can be rendered directly into the Sprint 50/53 screens without creating an AI dashboard, purple/blue gradient experience, or editor-first result.

## File Structure

- Modify: `backend/src/services/llm_router.py`
- Create: `backend/src/services/provider_adapters.py`
- Create: `backend/src/agents/schemas.py`
- Modify: `backend/src/agents/graph.py`
- Create: `backend/tests/test_provider_adapters.py`
- Create: `backend/tests/test_real_text_pipeline_contract.py`
- Modify: `.env.example`

## Tasks

### Task 1: Provider adapter 인터페이스 정의

**Files:**
- Create: `backend/src/services/provider_adapters.py`
- Test: `backend/tests/test_provider_adapters.py`

- [ ] **Step 1: Write failing test**

```python
from backend.src.services.provider_adapters import ProviderRequest, MockTextProvider


def test_mock_text_provider_returns_schema_compatible_json():
    provider = MockTextProvider()
    result = provider.generate_json(
        ProviderRequest(
            provider="mock",
            model="mock-text",
            system_prompt="system",
            user_prompt="user",
            schema_name="product_understanding",
        )
    )
    assert result["provider"] == "mock"
    assert isinstance(result["content"], dict)
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && uv run pytest tests/test_provider_adapters.py -v`  
Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement adapter contract**

Define:

- `ProviderRequest`
- `ProviderResult`
- `TextProviderProtocol`
- `MockTextProvider`

Do not call real OpenAI/Gemini/Claude in this task.

- [ ] **Step 4: Run test**

Run: `cd backend && uv run pytest tests/test_provider_adapters.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/provider_adapters.py backend/tests/test_provider_adapters.py
git commit -m "feat: define text provider adapter contract"
```

### Task 2: LLM 출력 스키마 추가

**Files:**
- Create: `backend/src/agents/schemas.py`
- Test: `backend/tests/test_real_text_pipeline_contract.py`

- [ ] **Step 1: Write failing schema test**

```python
from backend.src.agents.schemas import ProductUnderstandingOutput, SalesStrategyOutput


def test_product_understanding_schema_requires_facts():
    output = ProductUnderstandingOutput(
        product_type="유아 자전거",
        target_customer="첫 자전거를 찾는 부모",
        buyer_problem="안전한 첫 자전거 선택이 어렵다",
        verified_facts=["보조 바퀴 포함"],
        assumptions=["실내외 사용 가능"],
        risk_notes=[],
    )
    assert output.verified_facts == ["보조 바퀴 포함"]


def test_sales_strategy_schema_has_recommended_direction():
    output = SalesStrategyOutput(
        recommended_direction="문제 해결형",
        alternatives=["감성형", "스펙 강조형"],
        main_claim="처음 타는 순간부터 안정적인 자전거",
        support_claims=["보조 바퀴", "낮은 안장"],
        reason="초보 사용자의 구매 불안을 직접 해결한다",
    )
    assert output.recommended_direction == "문제 해결형"
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && uv run pytest tests/test_real_text_pipeline_contract.py -v`  
Expected: FAIL because schemas do not exist.

- [ ] **Step 3: Implement Pydantic schemas**

Add schemas for:

- `ProductUnderstandingOutput`
- `SalesStrategyOutput`
- `DetailPagePlanOutput`
- `CopySetOutput`
- `VisualPlanOutput`
- `QAReportOutput`

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_real_text_pipeline_contract.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/agents/schemas.py backend/tests/test_real_text_pipeline_contract.py
git commit -m "feat: add agent output schemas"
```

### Task 3: Real text pipeline adapter 연결

**Files:**
- Modify: `backend/src/agents/graph.py`
- Modify: `backend/src/services/llm_router.py`
- Test: `backend/tests/test_real_text_pipeline_contract.py`

- [ ] **Step 1: Add mocked real-mode test**

```python
from backend.src.agents.graph import AgentGraph
from backend.src.agents.state import AgentRunMode, AgentRunState, ProductInput
from backend.src.services.provider_adapters import MockTextProvider


def test_real_text_graph_uses_provider_without_image_generation():
    graph = AgentGraph.real_text(text_provider=MockTextProvider())
    state = AgentRunState(
        project_id="p1",
        mode=AgentRunMode.REAL,
        product_input=ProductInput(product_name="유아 자전거"),
    )
    completed = graph.run_text_generation(state)
    assert "product_understanding" in completed.outputs
    assert "sales_strategy" in completed.outputs
    assert "copy_set" in completed.outputs
    assert "generated_assets" not in completed.outputs
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && uv run pytest tests/test_real_text_pipeline_contract.py::test_real_text_graph_uses_provider_without_image_generation -v`  
Expected: FAIL.

- [ ] **Step 3: Implement real text graph path**

`AgentGraph.real_text` should:

- load prompts via `PromptRegistry`
- call `text_provider.generate_json`
- validate output with schemas
- keep image generation mocked or absent

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_provider_adapters.py tests/test_real_text_pipeline_contract.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/agents/graph.py backend/src/services/llm_router.py backend/tests/test_real_text_pipeline_contract.py
git commit -m "feat: connect real text generation pipeline"
```

## Done Criteria

- Real text pipeline can run through mocked provider adapter.
- OpenAI/Gemini/Claude selection is represented but not hardcoded into agent nodes.
- Image generation remains mock/skipped.
- No test requires real API keys.
