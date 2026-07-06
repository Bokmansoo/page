# Sellform Sprint 54 11-Agent LangGraph Architecture Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 순차형 `AgentGraph`를 11개 에이전트 폴더와 명확한 노드 인터페이스를 가진 LangGraph형 제작 파이프라인으로 재구성한다.

**Architecture:** 최종 제품 구조는 11개 에이전트 역할로 고정한다. Sprint 54는 외부 API 기능을 새로 늘리는 sprint가 아니라, 기존 mock/real text/image 흐름이 깨지지 않도록 보존하면서 `backend/src/agents/nodes/<agent_name>/` 단위로 책임을 분리하고 `graph.py`가 조건부 라우팅을 담당하게 만든다.

**Tech Stack:** FastAPI, Pydantic, existing agent graph, pytest, existing LLM/image services.

---

## File Structure

- Modify: `backend/src/agents/state.py`
- Modify: `backend/src/agents/schemas.py`
- Modify: `backend/src/agents/graph.py`
- Modify: `backend/src/agents/nodes/base.py`
- Create: `backend/src/agents/nodes/input_router/agent.py`
- Create: `backend/src/agents/nodes/input_router/schema.py`
- Create: `backend/src/agents/nodes/input_router/prompt.md`
- Create: `backend/src/agents/nodes/source_collection/agent.py`
- Create: `backend/src/agents/nodes/source_collection/schema.py`
- Create: `backend/src/agents/nodes/source_collection/prompt.md`
- Create: `backend/src/agents/nodes/product_understanding/agent.py`
- Create: `backend/src/agents/nodes/product_understanding/schema.py`
- Create: `backend/src/agents/nodes/product_understanding/prompt.md`
- Create: `backend/src/agents/nodes/reference_analysis/agent.py`
- Create: `backend/src/agents/nodes/reference_analysis/schema.py`
- Create: `backend/src/agents/nodes/reference_analysis/prompt.md`
- Create: `backend/src/agents/nodes/sales_strategy/agent.py`
- Create: `backend/src/agents/nodes/sales_strategy/schema.py`
- Create: `backend/src/agents/nodes/sales_strategy/prompt.md`
- Create: `backend/src/agents/nodes/page_planning/agent.py`
- Create: `backend/src/agents/nodes/page_planning/schema.py`
- Create: `backend/src/agents/nodes/page_planning/prompt.md`
- Create: `backend/src/agents/nodes/copywriting/agent.py`
- Create: `backend/src/agents/nodes/copywriting/schema.py`
- Create: `backend/src/agents/nodes/copywriting/prompt.md`
- Create: `backend/src/agents/nodes/visual_planning/agent.py`
- Create: `backend/src/agents/nodes/visual_planning/schema.py`
- Create: `backend/src/agents/nodes/visual_planning/prompt.md`
- Create: `backend/src/agents/nodes/image_generation/agent.py`
- Create: `backend/src/agents/nodes/image_generation/schema.py`
- Create: `backend/src/agents/nodes/image_generation/prompt.md`
- Create: `backend/src/agents/nodes/page_assembly/agent.py`
- Create: `backend/src/agents/nodes/page_assembly/schema.py`
- Create: `backend/src/agents/nodes/page_assembly/prompt.md`
- Create: `backend/src/agents/nodes/qa_review/agent.py`
- Create: `backend/src/agents/nodes/qa_review/schema.py`
- Create: `backend/src/agents/nodes/qa_review/prompt.md`
- Test: `backend/tests/test_11_agent_graph_contract.py`
- Test: `backend/tests/test_11_agent_node_contracts.py`

## Tasks

### Task 1: 11개 AgentStage와 상태 필드 확장

**Files:**
- Modify: `backend/src/agents/state.py`
- Test: `backend/tests/test_11_agent_graph_contract.py`

- [ ] **Step 1: Write failing stage-order test**

```python
from backend.src.agents.state import AgentStage


def test_11_agent_stage_order_is_final_product_pipeline():
    assert [stage.value for stage in AgentStage] == [
        "input_router",
        "source_collection",
        "product_understanding",
        "reference_analysis",
        "sales_strategy",
        "page_planning",
        "copywriting",
        "visual_planning",
        "image_generation",
        "page_assembly",
        "qa_review",
    ]
```

- [ ] **Step 2: Run test and verify failure**

Run: `cd backend && uv run pytest tests/test_11_agent_graph_contract.py::test_11_agent_stage_order_is_final_product_pipeline -v`  
Expected: FAIL because the current stage list is still the older pipeline shape.

- [ ] **Step 3: Update state model**

Update `AgentStage` with the 11 final node names. Add state fields if they are missing:

```python
class AgentRunState(BaseModel):
    project_id: str
    current_stage: AgentStage = AgentStage.INPUT_ROUTER
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    collected_sources: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    selected_image_candidates: dict[str, str] = Field(default_factory=dict)
    missing_inputs: list[str] = Field(default_factory=list)
    routing_hints: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run test and verify pass**

Run: `cd backend && uv run pytest tests/test_11_agent_graph_contract.py::test_11_agent_stage_order_is_final_product_pipeline -v`  
Expected: PASS.

### Task 2: 공통 노드 인터페이스 정의

**Files:**
- Modify: `backend/src/agents/nodes/base.py`
- Test: `backend/tests/test_11_agent_node_contracts.py`

- [ ] **Step 1: Write failing interface test**

```python
from backend.src.agents.nodes.base import AgentNode
from backend.src.agents.state import AgentRunState


class EchoNode(AgentNode):
    name = "echo"

    def run(self, state: AgentRunState) -> AgentRunState:
        state.outputs["echo"] = {"ok": True}
        return state


def test_agent_node_contract_returns_state():
    state = AgentRunState(project_id="project-1")
    result = EchoNode().run(state)
    assert result.outputs["echo"] == {"ok": True}
```

- [ ] **Step 2: Run test and verify failure**

Run: `cd backend && uv run pytest tests/test_11_agent_node_contracts.py::test_agent_node_contract_returns_state -v`  
Expected: FAIL if `AgentNode` is missing or incompatible.

- [ ] **Step 3: Implement base node**

```python
from abc import ABC, abstractmethod

from backend.src.agents.state import AgentRunState


class AgentNode(ABC):
    name: str

    @abstractmethod
    def run(self, state: AgentRunState) -> AgentRunState:
        raise NotImplementedError
```

- [ ] **Step 4: Run test and verify pass**

Run: `cd backend && uv run pytest tests/test_11_agent_node_contracts.py::test_agent_node_contract_returns_state -v`  
Expected: PASS.

### Task 3: 11개 노드 폴더와 stub agent 생성

**Files:**
- Create: all `backend/src/agents/nodes/<agent_name>/agent.py`
- Create: all `backend/src/agents/nodes/<agent_name>/schema.py`
- Create: all `backend/src/agents/nodes/<agent_name>/prompt.md`
- Test: `backend/tests/test_11_agent_node_contracts.py`

- [ ] **Step 1: Write failing import test**

```python
def test_all_11_agent_nodes_are_importable():
    from backend.src.agents.nodes.input_router.agent import InputRouterAgent
    from backend.src.agents.nodes.source_collection.agent import SourceCollectionAgent
    from backend.src.agents.nodes.product_understanding.agent import ProductUnderstandingAgent
    from backend.src.agents.nodes.reference_analysis.agent import ReferenceAnalysisAgent
    from backend.src.agents.nodes.sales_strategy.agent import SalesStrategyAgent
    from backend.src.agents.nodes.page_planning.agent import PagePlanningAgent
    from backend.src.agents.nodes.copywriting.agent import CopywritingAgent
    from backend.src.agents.nodes.visual_planning.agent import VisualPlanningAgent
    from backend.src.agents.nodes.image_generation.agent import ImageGenerationAgent
    from backend.src.agents.nodes.page_assembly.agent import PageAssemblyAgent
    from backend.src.agents.nodes.qa_review.agent import QAReviewAgent

    assert InputRouterAgent().name == "input_router"
    assert SourceCollectionAgent().name == "source_collection"
    assert ProductUnderstandingAgent().name == "product_understanding"
    assert ReferenceAnalysisAgent().name == "reference_analysis"
    assert SalesStrategyAgent().name == "sales_strategy"
    assert PagePlanningAgent().name == "page_planning"
    assert CopywritingAgent().name == "copywriting"
    assert VisualPlanningAgent().name == "visual_planning"
    assert ImageGenerationAgent().name == "image_generation"
    assert PageAssemblyAgent().name == "page_assembly"
    assert QAReviewAgent().name == "qa_review"
```

- [ ] **Step 2: Run test and verify failure**

Run: `cd backend && uv run pytest tests/test_11_agent_node_contracts.py::test_all_11_agent_nodes_are_importable -v`  
Expected: FAIL because the folders do not exist.

- [ ] **Step 3: Create node folders**

Each `agent.py` should subclass `AgentNode` and add a deterministic placeholder output under its own key. Example:

```python
from backend.src.agents.nodes.base import AgentNode
from backend.src.agents.state import AgentRunState


class InputRouterAgent(AgentNode):
    name = "input_router"

    def run(self, state: AgentRunState) -> AgentRunState:
        state.outputs[self.name] = {
            "input_type": "mixed",
            "missing_inputs": [],
        }
        return state
```

Each `prompt.md` must describe the agent role in Korean and explicitly say that mock mode must not call external providers.

- [ ] **Step 4: Run test and verify pass**

Run: `cd backend && uv run pytest tests/test_11_agent_node_contracts.py -v`  
Expected: PASS.

### Task 4: graph.py를 11개 노드 실행기로 전환

**Files:**
- Modify: `backend/src/agents/graph.py`
- Test: `backend/tests/test_11_agent_graph_contract.py`

- [ ] **Step 1: Write failing graph execution test**

```python
from backend.src.agents.graph import AgentGraph
from backend.src.agents.state import AgentRunState


def test_graph_runs_all_11_nodes_in_mock_mode():
    state = AgentRunState(
        project_id="project-1",
        input_snapshot={"product_name": "삼성 삼탠바이미 32인치 스마트모니터"},
    )
    result = AgentGraph.mock().run(state)

    assert list(result.outputs.keys()) == [
        "input_router",
        "source_collection",
        "product_understanding",
        "reference_analysis",
        "sales_strategy",
        "page_planning",
        "copywriting",
        "visual_planning",
        "image_generation",
        "page_assembly",
        "qa_review",
    ]
```

- [ ] **Step 2: Run test and verify failure**

Run: `cd backend && uv run pytest tests/test_11_agent_graph_contract.py::test_graph_runs_all_11_nodes_in_mock_mode -v`  
Expected: FAIL because the graph still uses the previous shape.

- [ ] **Step 3: Implement 11-node graph**

`AgentGraph.mock()` should instantiate the 11 agents in order. `run(state)` should call them sequentially and skip `reference_analysis` only when no URL/reference source exists. For this sprint, it is acceptable for the reference node to return `{"skipped": true}` so the frontend can still show a complete trace.

- [ ] **Step 4: Run test and verify pass**

Run: `cd backend && uv run pytest tests/test_11_agent_graph_contract.py -v`  
Expected: PASS.

### Task 5: 기존 생성 API와 호환성 유지

**Files:**
- Modify: `backend/src/agents/graph.py`
- Modify: existing generation API/service files that currently instantiate `AgentGraph`
- Test: existing generation tests

- [ ] **Step 1: Run existing tests before compatibility fix**

Run: `cd backend && uv run pytest tests/test_real_text_pipeline_contract.py tests/test_mock_generation_product_consistency.py tests/test_real_image_pipeline_contract.py -v`  
Expected: FAIL only if the old API expects previous graph output keys.

- [ ] **Step 2: Add compatibility output mapping**

Until the frontend is migrated, `AgentGraph.run()` must still expose the legacy keys used by the current UI:

```python
state.outputs["legacy"] = {
    "product_understanding": state.outputs["product_understanding"],
    "sales_strategy": state.outputs["sales_strategy"],
    "page_plan": state.outputs["page_planning"],
    "copy_set": state.outputs["copywriting"],
    "visual_plan": state.outputs["visual_planning"],
    "page_assembly": state.outputs["page_assembly"],
    "qa_report": state.outputs["qa_review"],
}
```

- [ ] **Step 3: Run compatibility tests**

Run: `cd backend && uv run pytest tests/test_real_text_pipeline_contract.py tests/test_mock_generation_product_consistency.py tests/test_real_image_pipeline_contract.py tests/test_11_agent_graph_contract.py tests/test_11_agent_node_contracts.py -v`  
Expected: PASS.

## Done Criteria

- `backend/src/agents/nodes/` contains 11 agent folders.
- Each agent has `agent.py`, `schema.py`, and `prompt.md`.
- `graph.py` runs the 11-node pipeline in mock mode without external API calls.
- URL/reference analysis has a clear skip path.
- Existing generated detail page flow still works through compatibility mapping.
- Existing real text and image tests still pass.
- The architecture reflects the final product structure, not an MVP shortcut.

