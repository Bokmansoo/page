# Sellform Sprint 48 Agent Architecture And Prompt Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AI 상세페이지 생성기의 기반이 되는 에이전트 상태, 실행 저장 구조, 노드 계약, 프롬프트 레지스트리, provider adapter, mock/real mode를 정의한다.

**Architecture:** 기존 Sprint 42~47 서비스를 직접 다시 쓰기보다, 새 `backend/src/agents` 계층에서 공통 상태와 노드 계약을 만들고 기존 서비스들을 노드 구현체로 감쌀 준비를 한다. DB에는 `AgentRun`/`AgentRunStep` 저장 구조를 추가해 한 번의 AI 생성 실행, 단계별 결과, 비용 승인, 실패/재시도 이력을 추적한다. 실제 GPT/API 호출은 하지 않고, Sprint 48은 구조/계약/mock 실행만 만든다.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, existing `llm_router`, pytest.

---

## DESIGN.md Alignment

Sprint 48 is mostly backend architecture, but it must still establish UI-facing contracts that support the Sellform design direction in `DESIGN.md`.

All generated state, stage labels, and prompt contracts should assume Sellform is a bright commerce creation service, not an AI technology dashboard.

Required contract implications:

- Stage names exposed to the frontend must be translatable into seller-friendly Korean labels such as `상품 이해`, `판매 포인트 정리`, `상세페이지 문구 작성`, `이미지 연출 계획`, and `상세페이지 초안 조립`.
- Agent outputs should avoid customer-facing wording like `agent execution`, `prompt workflow`, or raw model/provider terms.
- Prompt contracts should produce copy and visual planning data that can be rendered as a white-first, soft commerce detail page draft.
- The graph state should preserve source labels for uploaded, URL-extracted, mock-generated, and real-generated images so the UI can clearly label image provenance.
- No Sprint 48 contract should require an editor-first or dark dashboard-first experience.

Done Criteria addition:

- Backend contracts include enough seller-facing stage/result metadata for Sprint 49 and Sprint 50 to render the flow according to `DESIGN.md`.

## File Structure

- Create: `backend/src/agents/__init__.py`
- Create: `backend/src/agents/state.py`
- Create: `backend/src/agents/graph.py`
- Create: `backend/src/agents/nodes/__init__.py`
- Create: `backend/src/agents/nodes/base.py`
- Create: `backend/src/services/prompt_registry.py`
- Create: `backend/src/services/generation_mode.py`
- Modify: `backend/src/db/models.py`
- Modify: `backend/src/db/database.py`
- Create: `backend/tests/test_agent_state.py`
- Create: `backend/tests/test_agent_run_models.py`
- Create: `backend/tests/test_prompt_registry.py`
- Create: `backend/tests/test_agent_graph_contract.py`
- Modify: `backend/src/services/llm_router.py`
- Modify: `backend/src/config.py`
- Modify: `.env.example`

## Tasks

### Task 1: 생성 상태와 공통 데이터 계약 정의

**Files:**
- Create: `backend/src/agents/state.py`
- Test: `backend/tests/test_agent_state.py`

- [ ] **Step 1: Write failing tests**

```python
from backend.src.agents.state import (
    AgentStage,
    AgentRunMode,
    AgentRunState,
    ProductInput,
)


def test_agent_stage_order_contains_generation_flow():
    assert [stage.value for stage in AgentStage] == [
        "intake",
        "product_understanding",
        "missing_info_check",
        "sales_strategy",
        "user_strategy_confirmation",
        "page_planning",
        "copy_generation",
        "visual_planning",
        "image_cost_approval",
        "image_generation",
        "image_review",
        "page_assembly",
        "qa_review",
        "review_editor",
        "export_package",
    ]


def test_agent_run_state_defaults_to_mock_mode():
    state = AgentRunState(project_id="project-1", product_input=ProductInput(product_name="테스트 상품"))
    assert state.mode == AgentRunMode.MOCK
    assert state.current_stage == AgentStage.INTAKE
    assert state.errors == []
    assert state.cost_approval_status == "not_required"
    assert state.provider_trace == []
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && uv run pytest tests/test_agent_state.py -v`  
Expected: FAIL because `backend.src.agents.state` does not exist.

- [ ] **Step 3: Implement state contracts**

Create `backend/src/agents/state.py` with Pydantic models:

```python
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AgentRunMode(str, Enum):
    MOCK = "mock"
    REAL = "real"


class AgentStage(str, Enum):
    INTAKE = "intake"
    PRODUCT_UNDERSTANDING = "product_understanding"
    MISSING_INFO_CHECK = "missing_info_check"
    SALES_STRATEGY = "sales_strategy"
    USER_STRATEGY_CONFIRMATION = "user_strategy_confirmation"
    PAGE_PLANNING = "page_planning"
    COPY_GENERATION = "copy_generation"
    VISUAL_PLANNING = "visual_planning"
    IMAGE_COST_APPROVAL = "image_cost_approval"
    IMAGE_GENERATION = "image_generation"
    IMAGE_REVIEW = "image_review"
    PAGE_ASSEMBLY = "page_assembly"
    QA_REVIEW = "qa_review"
    REVIEW_EDITOR = "review_editor"
    EXPORT_PACKAGE = "export_package"


class ProductInput(BaseModel):
    product_name: str | None = None
    description: str | None = None
    product_url: str | None = None
    asset_ids: list[str] = Field(default_factory=list)
    reference_urls: list[str] = Field(default_factory=list)


class AgentRunState(BaseModel):
    run_id: str | None = None
    project_id: str
    mode: AgentRunMode = AgentRunMode.MOCK
    current_stage: AgentStage = AgentStage.INTAKE
    product_input: ProductInput
    outputs: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    cost_approval_status: str = "not_required"
    estimated_cost: float | None = None
    actual_cost: float | None = None
    provider_trace: list[dict[str, Any]] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify pass**

Run: `cd backend && uv run pytest tests/test_agent_state.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/agents/state.py backend/tests/test_agent_state.py
git commit -m "feat: define agent generation state"
```

### Task 2: AgentRun 영속화 모델 추가

**Files:**
- Modify: `backend/src/db/models.py`
- Modify: `backend/src/db/database.py`
- Test: `backend/tests/test_agent_run_models.py`

- [ ] **Step 1: Write failing persistence tests**

```python
from src.db.models import AgentRun, AgentRunStep, ProductProject, Brand


def test_agent_run_persists_generation_execution(db_session):
    brand = Brand(id="brand-agent-run", workspace_id="workspace-agent-run", name="Agent Brand")
    project = ProductProject(
        id="project-agent-run",
        workspace_id="workspace-agent-run",
        brand_id=brand.id,
        name="유아 자전거",
    )
    run = AgentRun(
        id="run-agent-1",
        workspace_id="workspace-agent-run",
        project_id=project.id,
        mode="mock",
        status="created",
        current_stage="intake",
        input_snapshot={"product_name": "유아 자전거"},
        outputs_json={},
        cost_approval_status="not_required",
        created_by="user-agent-run",
    )
    db_session.add_all([brand, project, run])
    db_session.commit()

    saved = db_session.query(AgentRun).filter_by(id="run-agent-1").one()
    assert saved.project_id == "project-agent-run"
    assert saved.workspace_id == "workspace-agent-run"
    assert saved.mode == "mock"
    assert saved.cost_approval_status == "not_required"


def test_agent_run_step_tracks_stage_output_and_cost(db_session):
    brand = Brand(id="brand-agent-step", workspace_id="workspace-agent-step", name="Agent Step Brand")
    project = ProductProject(
        id="project-agent-step",
        workspace_id="workspace-agent-step",
        brand_id=brand.id,
        name="유아 자전거",
    )
    run = AgentRun(
        id="run-agent-step",
        workspace_id="workspace-agent-step",
        project_id=project.id,
        mode="mock",
        status="running",
        current_stage="product_understanding",
        input_snapshot={"product_name": "유아 자전거"},
        outputs_json={},
        cost_approval_status="not_required",
        created_by="user-agent-step",
    )
    step = AgentRunStep(
        id="step-agent-1",
        run_id=run.id,
        stage="product_understanding",
        status="completed",
        input_json={"product_name": "유아 자전거"},
        output_json={"product_type": "kids_bicycle"},
        provider="mock",
        model="deterministic",
        prompt_version="sprint-48",
        token_usage={"input": 0, "output": 0},
        estimated_cost=0.0,
    )
    db_session.add_all([brand, project, run, step])
    db_session.commit()

    saved = db_session.query(AgentRunStep).filter_by(id="step-agent-1").one()
    assert saved.run_id == "run-agent-step"
    assert saved.output_json["product_type"] == "kids_bicycle"
    assert saved.estimated_cost == 0.0
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && uv run pytest tests/test_agent_run_models.py -v`  
Expected: FAIL because `AgentRun` and `AgentRunStep` do not exist.

- [ ] **Step 3: Add SQLAlchemy models**

Add these models to `backend/src/db/models.py`:

```python
class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False)
    mode = Column(String(20), nullable=False, default="mock")
    status = Column(String(50), nullable=False, default="created")
    current_stage = Column(String(80), nullable=False, default="intake")
    input_snapshot = Column(JSON, nullable=False, default=dict)
    outputs_json = Column(JSON, nullable=False, default=dict)
    cost_approval_status = Column(String(50), nullable=False, default="not_required")
    estimated_cost = Column(Float, nullable=True)
    actual_cost = Column(Float, nullable=True)
    provider_trace = Column(JSON, nullable=False, default=list)
    error_log = Column(JSON, nullable=False, default=list)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    project = relationship("ProductProject")
    workspace = relationship("Workspace")
    user = relationship("User")
    steps = relationship("AgentRunStep", back_populates="run", cascade="all, delete-orphan")


class AgentRunStep(Base):
    __tablename__ = "agent_run_steps"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    stage = Column(String(80), nullable=False)
    status = Column(String(50), nullable=False, default="pending")
    input_json = Column(JSON, nullable=False, default=dict)
    output_json = Column(JSON, nullable=False, default=dict)
    provider = Column(String(50), nullable=True)
    model = Column(String(100), nullable=True)
    prompt_version = Column(String(100), nullable=True)
    token_usage = Column(JSON, nullable=True)
    estimated_cost = Column(Float, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    run = relationship("AgentRun", back_populates="steps")
```

- [ ] **Step 4: Add runtime schema compatibility**

In `backend/src/db/database.py`, extend `ensure_runtime_schema_compatibility()` only if the local database already exists and the tables are missing. Use `Base.metadata.create_all(bind=engine)` for new test databases and add a lightweight guard for older local DBs:

```python
if "agent_runs" not in table_names or "agent_run_steps" not in table_names:
    Base.metadata.create_all(bind=engine)
```

- [ ] **Step 5: Run persistence tests**

Run: `cd backend && uv run pytest tests/test_agent_run_models.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/db/models.py backend/src/db/database.py backend/tests/test_agent_run_models.py
git commit -m "feat: persist agent generation runs"
```

### Task 3: 프롬프트 레지스트리 정의

**Files:**
- Create: `backend/src/services/prompt_registry.py`
- Create: `backend/prompts/system/sellform_agent_base.md`
- Create: `backend/prompts/agents/product_understanding.md`
- Create: `backend/prompts/agents/sales_strategy.md`
- Create: `backend/prompts/agents/page_planning.md`
- Create: `backend/prompts/agents/copywriting.md`
- Create: `backend/prompts/agents/visual_planning.md`
- Create: `backend/prompts/agents/qa_review.md`
- Test: `backend/tests/test_prompt_registry.py`

- [ ] **Step 1: Write failing tests**

```python
from backend.src.services.prompt_registry import PromptRegistry


def test_prompt_registry_loads_named_prompt():
    registry = PromptRegistry(base_path="backend/prompts")
    prompt = registry.load("agents/product_understanding")
    assert "상품" in prompt
    assert "검증된 사실" in prompt


def test_prompt_registry_rejects_path_traversal():
    registry = PromptRegistry(base_path="backend/prompts")
    try:
        registry.load("../.env")
    except ValueError as exc:
        assert "Invalid prompt name" in str(exc)
    else:
        raise AssertionError("path traversal should be rejected")
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && uv run pytest tests/test_prompt_registry.py -v`  
Expected: FAIL because `PromptRegistry` does not exist.

- [ ] **Step 3: Implement registry and prompt files**

Create `PromptRegistry.load(name: str) -> str` that resolves only `.md` files under `backend/prompts`. Add Korean prompt skeletons with explicit JSON-output intent. For example `backend/prompts/agents/product_understanding.md` starts with:

```markdown
# 상품 이해 에이전트

너는 1인 셀러를 돕는 Sellform AI MD다.
입력된 상품 사진, URL, 상품명, 설명을 바탕으로 상품을 이해한다.

반드시 다음을 분리한다.
- 검증된 사실
- 추정
- 사용자 확인이 필요한 정보
- 위험하거나 금지해야 할 주장
```

- [ ] **Step 4: Run test to verify pass**

Run: `cd backend && uv run pytest tests/test_prompt_registry.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/prompt_registry.py backend/prompts backend/tests/test_prompt_registry.py
git commit -m "feat: add sellform prompt registry"
```

### Task 4: mock/real mode와 provider adapter 계약 추가

**Files:**
- Create: `backend/src/services/generation_mode.py`
- Modify: `backend/src/services/llm_router.py`
- Modify: `backend/src/config.py`
- Modify: `.env.example`
- Test: `backend/tests/test_generation_mode.py`

- [ ] **Step 1: Write failing tests**

```python
from backend.src.services.generation_mode import GenerationMode, resolve_generation_mode


def test_generation_mode_defaults_to_mock(monkeypatch):
    monkeypatch.delenv("SELLFORM_GENERATION_MODE", raising=False)
    assert resolve_generation_mode() == GenerationMode.MOCK


def test_generation_mode_accepts_real(monkeypatch):
    monkeypatch.setenv("SELLFORM_GENERATION_MODE", "real")
    assert resolve_generation_mode() == GenerationMode.REAL
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && uv run pytest tests/test_generation_mode.py -v`  
Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement mode resolver and config defaults**

Create `GenerationMode` enum with `mock` and `real`. Add `.env.example`:

```dotenv
SELLFORM_GENERATION_MODE=mock
SELLFORM_TEXT_LLM_PRIMARY_PROVIDER=openai
SELLFORM_TEXT_LLM_FALLBACK1_PROVIDER=gemini
SELLFORM_TEXT_LLM_FALLBACK2_PROVIDER=claude
SELLFORM_IMAGE_PRIMARY_PROVIDER=openai
```

Keep `llm_router` provider-neutral. Do not call external providers in mock mode.

- [ ] **Step 4: Run test to verify pass**

Run: `cd backend && uv run pytest tests/test_generation_mode.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/generation_mode.py backend/src/services/llm_router.py backend/src/config.py .env.example backend/tests/test_generation_mode.py
git commit -m "feat: add generation mode and provider contract"
```

### Task 5: 에이전트 그래프 골격 추가

**Files:**
- Create: `backend/src/agents/graph.py`
- Create: `backend/src/agents/nodes/base.py`
- Create: `backend/src/agents/nodes/__init__.py`
- Create: `backend/src/agents/__init__.py`
- Test: `backend/tests/test_agent_graph_contract.py`

- [ ] **Step 1: Write failing tests**

```python
from backend.src.agents.graph import AgentGraph
from backend.src.agents.state import AgentRunState, AgentStage, ProductInput


def test_mock_graph_advances_from_intake_to_product_understanding():
    graph = AgentGraph.mock()
    state = AgentRunState(project_id="p1", product_input=ProductInput(product_name="유아 자전거"))
    next_state = graph.run_next(state)
    assert next_state.current_stage == AgentStage.PRODUCT_UNDERSTANDING
    assert "product_understanding" in next_state.outputs
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && uv run pytest tests/test_agent_graph_contract.py -v`  
Expected: FAIL because `AgentGraph` does not exist.

- [ ] **Step 3: Implement minimal mock graph**

Implement `AgentGraph.mock().run_next(state)` with deterministic mock output for only `INTAKE -> PRODUCT_UNDERSTANDING`. Later sprints add the full pipeline.

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_agent_state.py tests/test_agent_graph_contract.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/agents backend/tests/test_agent_graph_contract.py
git commit -m "feat: add mock agent graph contract"
```

## Done Criteria

- Agent state model exists and defaults to mock mode.
- Agent state includes run ID, cost approval status, estimated/actual cost, and provider trace fields.
- `AgentRun` and `AgentRunStep` SQLAlchemy models persist AI generation execution state and stage-level outputs.
- Agent run persistence keeps `workspace_id` and `project_id` on the run for workspace isolation.
- Stage output, provider, model, prompt version, token usage, cost, and error fields can be stored per run step.
- Prompt registry loads only approved prompt files.
- Provider strategy is represented in config and does not trigger API calls in mock mode.
- Mock agent graph can advance at least one stage.
- Final architecture has an explicit place for project deletion, asset deletion, final version selection, and API cost tracing to be handled in later sprints.
- All Sprint 48 tests pass.
