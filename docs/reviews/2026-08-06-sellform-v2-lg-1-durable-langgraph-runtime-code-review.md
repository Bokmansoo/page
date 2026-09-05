# 코드리뷰: Sellform V2 LG-1 Durable LangGraph Runtime

검토일: 2026-08-06  
상태: **승인 — LG-2 진행 가능**  
관련 계획: [LG-1 Durable LangGraph Runtime](../superpowers/plans/2026-08-06-sellform-v2-lg-1-durable-langgraph-runtime.md)  
상위 로드맵: [LangGraph 전환 Sprint 로드맵](../superpowers/plans/2026-08-06-sellform-v2-langgraph-migration-roadmap.md)

## 1. 검토 범위

- `backend/pyproject.toml`, `backend/uv.lock`
- `backend/src/agents/langgraph_runtime.py`
- `backend/src/services/langgraph_run_service.py`
- `backend/src/api/graph_runs.py`
- `backend/src/db/models.py`, `backend/src/db/database.py`
- `backend/src/config.py`, `backend/.env.example`
- `backend/tests/test_lg1_durable_graph_runtime.py`

## 2. 완료 조건별 결과

| LG-1 요구 | 구현 증거 | 결과 |
| --- | --- | --- |
| JSON 직렬화 가능 `SellformGraphState` | ID·승인 입력·상태·이벤트·오류만 포함, raw secret/ORM/provider 객체 미포함 | 통과 |
| 실제 `StateGraph(...).compile(checkpointer=...)` | 3-node LG-1 graph를 explicit saver로 컴파일 | 통과 |
| PostgreSQL checkpointer factory | `PostgresSaver.from_conn_string()`과 `psycopg[binary]` lock | 통과 |
| node별 state history | `get_state`, `get_state_history` API/service와 graph history 테스트 | 통과 |
| 서버 재시작 수준 복구 | 첫 PostgreSQL connection에서 첫 node 뒤 중단 후 두 번째 connection에서 남은 node 실행 | 통과 |
| `thread_id=AgentRun.id` | 저장 필드·service 계약·API 테스트 | 통과 |
| `AgentRun`/`AgentRunStep` projection | `AgentRunGraphProjector`가 graph event를 upsert | 통과 |
| `current_stage`의 graph event 전용 변경 | graph start 경로에서 projector만 `current_stage` 변경 | 통과 |
| start 멱등성 | 실행 중 실제 동시 start에서 하나만 execution lease를 획득 | 통과 |
| start/get/history/cancel/resume 계약 | `/api/v1/graph-runs/{run_id}/...` | 통과 |
| 기존 생성 흐름 보존 | 기존 11-agent와 agent-run API 회귀 테스트 | 통과 |

## 3. 핵심 검토 사항

### PostgreSQL을 명시적으로 요구

`open_postgres_checkpointer()`는 SQLite나 in-memory saver로 조용히 fallback하지 않는다. 운영용 durable 실행은 PostgreSQL URL이 아니면 명확히 실패한다. `InMemorySaver`는 테스트에서만 의존성으로 주입된다. 따라서 재시작 복구가 필요한 run이 실수로 휘발성 저장소를 사용하는 문제가 없다.

### 하나의 run, 하나의 thread

`AgentRun.id` 자체가 graph thread ID다. 별도의 임의 UUID를 만들지 않으며 `graph_thread_id`가 다른 값이면 service가 거부한다. checkpoint ID는 운영 조회를 위해 `AgentRun`에 projection한다.

### projection과 원본 상태의 책임 분리

LangGraph checkpoint는 실행 위치와 상태 history의 원본이다. `AgentRun`과 `AgentRunStep`은 UI·운영 조회를 위한 projection이다. 각 node update는 `events`에 구조화 event를 반환하고, projector가 그 event의 stage만 사용해 `current_stage`를 갱신한다.

### 실패 복구와 resume 계약

LG-1 graph에는 아직 사람 승인 interrupt가 없다. 그러나 checkpoint 또는 SQL projection 실패 뒤 `resume`은 같은 `thread_id`의 state history를 먼저 replay해 누락된 `AgentRunStep` projection을 복구하고, 남은 node만 실제 실행한다. final checkpoint까지 기록된 뒤 장애가 발생한 경우에는 node를 다시 실행하지 않고 projection과 checkpoint ID만 복구한다. 실제 `Command(resume=...)`와 승인 대기는 LG-4에서 도입한다.

### 동시 실행과 취소

`start`와 `resume`은 상태 조건부 update로 execution lease를 획득한다. 따라서 두 번째 요청은 `running` 상태를 확인하고 graph를 다시 invoke하지 않는다. 각 node event projection은 run 행을 잠그고 취소 상태를 먼저 확인하므로, 늦게 도착한 event가 `cancelled` 상태를 다시 `running` 또는 `completed`로 덮어쓰지 못한다.

## 4. 테스트 결과

실행 명령:

```powershell
cd C:\page\backend
.\.venv\Scripts\python.exe -m pytest tests/test_lg0_langgraph_runtime.py tests/test_lg0_legacy_characterization.py tests/test_lg1_durable_graph_runtime.py tests/test_11_agent_graph_contract.py tests/test_11_agent_node_contracts.py tests/test_agent_graph_contract.py tests/test_agent_run_api.py -q
uv lock --locked
```

결과: **29 passed**, lockfile 일치 확인 완료.

추가로 실제 PostgreSQL에 `agent_runs.graph_thread_id`, `agent_runs.graph_checkpoint_id` 호환 컬럼이 생성됐는지 확인했다.

기존 FastAPI/Starlette, Google Generative AI, Pydantic 설정, `datetime.utcnow` deprecation 경고는 남아 있지만, LG-1의 실행·복구·저장 계약 실패는 아니다. 별도 유지보수 범위다.

## 5. 결론

LG-1 기획의 완료 조건은 모두 충족했다. 실제 PostgreSQL 체크포인터, 중단 지점에서 같은 thread의 재연결 재개, 실패한 projection의 복구, `AgentRun`/`AgentRunStep` projection, 동시 start 멱등성, 취소 보호, 조회·복구 resume API 계약이 구현·검증됐다.

다음 Sprint는 **LG-2: Discovery subgraph**다. Input Router, Source Collection, Product Understanding, Reference Analysis를 실제 LangGraph node로 전환한다.
