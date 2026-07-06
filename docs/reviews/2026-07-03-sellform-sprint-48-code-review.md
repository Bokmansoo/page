# 코드 리뷰: Sellform Sprint 48 Agent Architecture And Prompt Contracts

| 항목 | 내용 |
| --- | --- |
| 브랜치 | `master` |
| 리뷰 일자 | 2026-07-03 |
| 리뷰 범위 | AgentRunState, AgentRun, AgentRunStep, PromptRegistry, GenerationMode, AgentGraph |
| 관련 기획·작업 | [2026-07-03-sellform-sprint-48-agent-architecture-prompt-contracts.md](file:///C:/page/docs/superpowers/plans/2026-07-03-sellform-sprint-48-agent-architecture-prompt-contracts.md) |
| 리뷰어 | Antigravity AI |
| 상태 | 승인 |

## 1. 변경 요약

- 상세페이지 생성 파이프라인의 에이전트 실행 상태를 관리하는 **`AgentRunState`** 및 **15개 핵심 생성 단계(`AgentStage`)**를 Pydantic Schema로 정의했습니다.
- 에이전트 실행 이력을 격리 추적하기 위한 **`AgentRun`** 및 **`AgentRunStep`** SQLAlchemy DB 모델을 추가하고, 기존 로컬 DB 테이블과의 하위 호환성을 유지하며 자동으로 마이그레이션하도록 데이터베이스 헬퍼를 갱신했습니다.
- 상위 디렉터리 경로 탐색 공격(Path Traversal)을 엄격히 방어하는 안전한 **`PromptRegistry`** 서비스를 구현하고, 에이전트 기본 시스템 프롬프트를 포함한 마크다운 기반 프롬프트 스켈레톤 7종을 패키징했습니다.
- 개발 환경의 비용 유출 및 원치 않는 외부 호출을 방지하기 위해 `mock` 모드 설정 시 외부 API 어댑터 호출을 배제하고 즉시 deterministic 로컬 룰로 폴백하게 만드는 **`LLMRouter`** 모드 가드 처리를 도입했습니다.
- `INTAKE` -> `PRODUCT_UNDERSTANDING` 단계의 mock 전이 로직을 내장한 공통 에이전트 그래프(**`AgentGraph`**) 골격을 구현하여 향후 스프린트의 비즈니스 오케스트레이터 연계를 준비했습니다.

## 2. 검토한 범위와 핵심 흐름

### 검토한 자료

- **기획 문서**: [2026-07-03-sellform-sprint-48-agent-architecture-prompt-contracts.md](file:///C:/page/docs/superpowers/plans/2026-07-03-sellform-sprint-48-agent-architecture-prompt-contracts.md)
- **추가/수정 코드**:
  - [state.py](file:///C:/page/backend/src/agents/state.py)
  - [graph.py](file:///C:/page/backend/src/agents/graph.py)
  - [base.py](file:///C:/page/backend/src/agents/nodes/base.py)
  - [models.py](file:///C:/page/backend/src/db/models.py)
  - [database.py](file:///C:/page/backend/src/db/database.py)
  - [prompt_registry.py](file:///C:/page/backend/src/services/prompt_registry.py)
  - [generation_mode.py](file:///C:/page/backend/src/services/generation_mode.py)
  - [llm_router.py](file:///C:/page/backend/src/services/llm_router.py)
  - [config.py](file:///C:/page/backend/src/config.py)
  - [.env.example](file:///C:/page/.env.example)
- **테스트 파일**:
  - [test_agent_state.py](file:///C:/page/backend/tests/test_agent_state.py)
  - [test_agent_run_models.py](file:///C:/page/backend/tests/test_agent_run_models.py)
  - [test_prompt_registry.py](file:///C:/page/backend/tests/test_prompt_registry.py)
  - [test_generation_mode.py](file:///C:/page/backend/tests/test_generation_mode.py)
  - [test_agent_graph_contract.py](file:///C:/page/backend/tests/test_agent_graph_contract.py)

### 핵심 흐름

```text
[ProductInput] -> [AgentRunState] -> [AgentGraph.run_next] -> [AgentStage.PRODUCT_UNDERSTANDING]
                       ↓ (DB Persistence)
             [AgentRun / AgentRunStep]
```

- **에이전트 실행 상태 관리**: 전체 상세페이지 파이프라인의 15단계 천이 과정을 `AgentStage` enum으로 추적하며, `AgentRunState`를 통해 단계별 모의(mock) 연산 결과(`outputs`), 발생 에러(`errors`), 그리고 API 호출 트레이스(`provider_trace`)를 투명하게 수집합니다.
- **영속화 격리**: `workspace_id`와 `project_id`를 `AgentRun` 모델에 상속 보존하여 워크스페이스별 다중 프로젝트 생성 실행 기록을 안전하게 격리 저장합니다.
- **안전한 프롬프트 주입**: 에이전트 시스템에 탑재되는 프롬프트는 로컬 프롬프트 파일(`.md`) 경로에 한해서만 `PromptRegistry`에 의해 검증 로드됩니다.

## 3. 이슈 목록

심각도: 🔴 Blocker · 🟠 Major · 🟡 Minor · ⚪ Nit

### ⚪ N1. 로컬 pytest 실행 시 PYTHONPATH 설정 필요 권고
- **위치**: `pytest` 실행 환경 구성
- **내용**: 백엔드 코드의 상위 패키지 임포트 경로(`backend.src...`)의 영향으로 `backend/` 폴더 진입 상태에서 단순 `pytest` 호출 시 모듈 탐색 실패 에러가 발생할 수 있습니다.
- **영향**: 개발자 로컬 머신에서 CLI 테스트 실패를 유발할 수 있습니다.
- **제안**: 로컬 테스트 구동 시 프로젝트 루트 디렉터리(`C:\page`)를 기준으로 환경변수 `PYTHONPATH`를 지정하여 `uv run --project backend pytest backend/tests/...` 방식으로 실행할 것을 권장합니다.
> **[조치 상태 - 2026-07-03]** 본 코드리뷰 및 워크스루 빌드 가이드에 해당 실행법 지침을 기술했습니다.

## 4. 우선순위 권고

1. **⚪ N1 (PYTHONPATH 설정)** — 로컬 개발 생산성 향상을 위한 사항으로 빌드 가이드 문서 정비를 권장합니다.

## 5. 긍정적인 부분

- **Path Traversal 보안 방어**: 사용자 인풋 또는 변조된 에이전트 명칭 조작을 통해 발생 가능한 디렉터리 탐색 취약점(`../.env` 접근 등)을 원천 차단하도록 `PromptRegistry`에 경로 정규화 및 상속 가드를 구현했습니다.
- **의도치 않은 외부 요금 과금 방지**: `SELLFORM_GENERATION_MODE=mock`일 때, 라우터가 외부 LLM API(OpenAI, Gemini 등) 어댑터를 절대 구동하지 않고 즉시 로컬 deterministic 룰 기반 연산만 타게 함으로써 안전한 로컬 오프라인 개발이 가능해졌습니다.

## 6. AI·사실 신뢰성 검토

- 프롬프트 뼈대 내에 명시적인 지침("반드시 다음을 분리한다: 검증된 사실, 추정, 사용자 확인 필요 정보, 위험 주장")을 내포시킴으로써, 향후 실 서비스 에이전트 구현 시 환각(Hallucination)을 제어하고 입력된 사실 에셋에만 의존하게 만드는 프롬프트 계약을 수립했습니다.

## 7. 검증 증적

### 자동 테스트
새로 신설된 5종의 계약 및 단위 테스트를 수행하여 모든 단일 기능과 영속화, 경로 방어 동작이 정상 완료됨을 검증했습니다.

```text
backend\tests\test_agent_state.py::test_agent_stage_order_contains_generation_flow PASSED
backend\tests\test_agent_state.py::test_agent_run_state_defaults_to_mock_mode PASSED
backend\tests\test_agent_run_models.py::test_agent_run_persists_generation_execution PASSED
backend\tests\test_agent_run_models.py::test_agent_run_step_tracks_stage_output_and_cost PASSED
backend\tests\test_prompt_registry.py::test_prompt_registry_loads_named_prompt PASSED
backend\tests\test_prompt_registry.py::test_prompt_registry_rejects_path_traversal PASSED
backend\tests\test_generation_mode.py::test_generation_mode_defaults_to_mock PASSED
backend\tests\test_generation_mode.py::test_generation_mode_accepts_real PASSED
backend\tests\test_agent_graph_contract.py::test_mock_graph_advances_from_intake_to_product_understanding PASSED

======================= 9 passed, 18 warnings in 0.44s ========================
```
