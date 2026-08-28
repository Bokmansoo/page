# 코드리뷰: Sellform V2 LG-0 LangGraph 기반 준비

검토일: 2026-08-06  
상태: **승인 — LG-1 진행 가능**  
관련 기획: [LG-0 전환 로드맵](../superpowers/plans/2026-08-06-sellform-v2-langgraph-migration-roadmap.md)  
상위 설계: [실제 LangGraph 멀티에이전트 시스템 최종 기획](../superpowers/specs/2026-08-06-sellform-v2-langgraph-agent-system-final-design.md)  
결정 기록: [LangGraph 실행기와 체크포인트 책임 경계](../decisions/2026-08-06-sellform-langgraph-runtime-and-checkpoint-boundary.md)

## 1. 검토 범위

LG-0은 기존 판매 상세페이지 생성 기능을 즉시 전환하는 Sprint가 아니다. 기존 `AgentGraph` 생성 경로를 보존한 상태에서 실제 LangGraph 의존성, 컴파일 가능한 최소 그래프, 안전한 체크포인트 입력 계약, 이후 전환의 기준선을 마련하는 Sprint다.

검토 대상은 다음과 같다.

- `backend/pyproject.toml`, `backend/uv.lock`
- `backend/src/config.py`, `backend/.env.example`
- `backend/src/agents/langgraph_runtime.py`
- `backend/src/agents/schemas.py`
- `backend/tests/test_lg0_langgraph_runtime.py`
- `backend/tests/test_lg0_legacy_characterization.py`
- 기존 11-agent·agent-run 계약 테스트
- [LangGraph 실행기와 체크포인트 책임 경계](../decisions/2026-08-06-sellform-langgraph-runtime-and-checkpoint-boundary.md)

## 2. 기획 대비 구현 확인

| LG-0 요구 | 구현 증거 | 결과 |
| --- | --- | --- |
| 실제 LangGraph 의존성 추가 | `langgraph`, `langgraph-checkpoint-postgres`와 lockfile 반영 | 통과 |
| 기존 경로를 기본값으로 보존 | `SELLFORM_GRAPH_RUNTIME`의 기본값이 `legacy` | 통과 |
| 실제 컴파일 그래프 smoke test | `StateGraph`의 `bootstrap_run → finalize_run` 컴파일·invoke | 통과 |
| 체크포인트 상태의 비밀값 차단 | allowlist 및 `input_snapshot` reducer를 모두 적용 | 통과 |
| helper 우회 호출에도 비밀값 차단 | raw graph input으로 API 키·Authorization을 주입하는 회귀 테스트 | 통과 |
| 11-agent 골든 경로 기준선 | 실제 11개 stage 순서, 산출물 Pydantic 계약, legacy 호환 필드를 검증 | 통과 |
| 외부 AI provider 비호출 보장 | OpenAI 텍스트·이미지 provider를 실패하도록 대체해도 mock 경로 완주 | 통과 |
| 기존 생성 진입점과 직접 조립 경로 식별 | 아래 목록 및 ADR의 책임 경계 표 | 통과 |
| 향후 저장 책임·보안 결정 기록 | 새 ADR 작성, 기존 비도입 기준 ADR을 대체됨으로 표기 | 통과 |

## 3. 구현 검토

### 3.1 실제 LangGraph 기반

`langgraph_runtime.py`는 이름만 graph인 래퍼가 아니라 LangGraph의 `StateGraph`, `START`, `END`를 사용한다. 최소 그래프는 `bootstrap_run → finalize_run`으로 컴파일되며 `InMemorySaver` 체크포인터로 invoke할 수 있다.

LG-0에서는 의도적으로 기존 `AgentGraph`를 호출하지 않는다. 이 Sprint의 목표는 실제 생성 로직의 전환이 아니라 안전한 실행 기반의 도입이기 때문이다. 실제 run의 routing과 `AgentRun` 투영은 LG-1 범위다.

### 3.2 기능 플래그와 기존 경로 보존

`SELLFORM_GRAPH_RUNTIME`은 `legacy | langgraph`만 허용하며 기본값은 `legacy`다. 빈 환경파일로 `Settings`를 생성하는 테스트도 이 기본값을 검증한다. 따라서 기존 화면, API, 저장 결과는 LG-0 적용만으로 바뀌지 않는다.

### 3.3 체크포인트 보안 경계

체크포인트에는 제품명, 프로젝트 식별자, 승인된 사실 ID, 자산 ID 등 허용된 입력만 기록한다. `checkpoint_safe_input_snapshot()`은 deep copy와 allowlist를 사용하고, `LG0GraphState.input_snapshot` reducer도 동일한 정제를 강제한다. 즉 호출자가 helper를 거치지 않고 raw 상태를 `invoke()`해도 `OPENAI_API_KEY`, Authorization 같은 필드는 저장 상태에 남지 않는다.

### 3.4 11-agent 골든 경로와 구조화 출력

`test_lg0_legacy_characterization.py`는 mock 11-agent 흐름을 실제로 실행해 다음을 고정했다.

- `intake`부터 `qa_review`까지 11개 stage의 순서
- 제품 이해, 판매 전략, 상세페이지 계획, 카피, 비주얼, QA 산출물의 Pydantic 계약
- 이미지 작업·후보와 페이지 섹션의 legacy 호환 필드
- mock 실행 중 OpenAI 텍스트·이미지 provider가 호출되지 않는 조건

이 기준선에서 QA export gate가 문자열 목록으로 선언된 `warnings`에 구조화 경고 객체를 추가하는 불일치를 발견했다. `QAWarning` 모델과 `List[str | QAWarning]` 계약으로 바로잡아, 현재 실제 산출물과 스키마가 일치한다.

### 3.5 현재 생성 진입점·직접 조립 경로

LG-0 시점에는 아래 경로가 모두 legacy 구현을 사용한다. LG-1은 이 목록을 기준으로 LangGraph thread와 `AgentRun` projection을 연결한다.

| 구분 | 현재 진입점 또는 경로 | 현재 책임 |
| --- | --- | --- |
| 에이전트 run 생성 | `POST /api/agent-runs` | run 레코드 생성 |
| mock 실행 | `POST /api/agent-runs/{id}/run-mock` → `AgentRunService.run_mock` → `AgentGraph` | 11-agent mock 실행 |
| 실제 실행 | `AgentRunService.run_real` → `AgentGraph` | provider 기반 생성 실행 |
| 기획 승인 | `POST /api/v1/projects/{project_id}/planning-draft/approve` | 기획 데이터·이미지 작업을 직접 조립 |
| 비주얼 생성 | visual job generate 경로 | 이미지 작업 생성·실행 |
| 스토리보드 | storyboard start/approve 경로 | 장면 승인 상태 관리 |
| 이미지 승인 | `images/approve-cost` | 비용 확인 및 이미지 승인 |
| 페이지 조립·편집 | `/api/v1/projects/{project_id}/page*`, `page/sections/*/ai-edit` | 상세페이지 버전·섹션 직접 조립 |

정확한 API 경로, 저장소별 책임, 체크포인트에 저장하지 않을 데이터는 ADR을 단일 기준으로 관리한다.

## 4. 테스트 결과

실행 명령:

```powershell
cd C:\page\backend
.\.venv\Scripts\python.exe -m pytest tests/test_lg0_langgraph_runtime.py tests/test_lg0_legacy_characterization.py tests/test_11_agent_graph_contract.py tests/test_11_agent_node_contracts.py tests/test_agent_graph_contract.py tests/test_agent_run_api.py -q
```

결과: **19 passed**

검증한 항목:

- 실제 LangGraph 그래프 컴파일·invoke
- 기능 플래그의 legacy 기본값과 langgraph opt-in
- helper 경유·우회 호출 모두에서의 체크포인트 비밀값 차단
- allowlist snapshot의 deep copy 보장
- 실제 11-agent mock stage 순서와 구조화 산출물 계약
- 외부 OpenAI text/image provider가 호출되지 않는 mock 골든 경로
- 기존 agent-run 생성·실행·상태 API 계약

테스트 실행 중 FastAPI/Starlette HTTPX, Google Generative AI, Pydantic 설정, `datetime.utcnow` 관련 기존 deprecation 경고가 나타난다. 모두 기존 코드의 경고이며 LG-0 실패나 비밀값 노출은 아니다. 별도 유지보수 항목으로 관리한다.

## 5. 의도적으로 다음 Sprint에 남긴 범위

아래는 LG-0 누락이 아니라 후속 Sprint 범위다.

- PostgreSQL checkpointer factory와 운영 DB 설정: LG-1
- `AgentRun`과 LangGraph thread의 실행·투영 adapter: LG-1
- 11개 에이전트의 실제 LangGraph node 전환: LG-2 ~ LG-6
- `interrupt`와 `Command(resume=...)` 승인 흐름: LG-4
- 이미지 provider worker·정책 게이트 연결: LG-5
- QA 조건부 재시작과 page version 고정: LG-6
- 이벤트 스트리밍, 재시도·복구, legacy 쓰기 경로 제거: LG-7 ~ LG-8

## 6. 코드리뷰 결론

LG-0의 완료 조건은 모두 충족했다. 실제 LangGraph 기반, legacy 기본 보존, helper 우회까지 포함한 체크포인트 보안, 11-agent 골든 경로의 구조화 계약, 외부 provider를 호출하지 않는 기준선, 진입점·저장 책임 ADR이 갖춰졌다.

다음 작업은 **LG-1: LangGraph thread·PostgreSQL 체크포인터와 `AgentRun` projection 연결**이다. LG-1 완료 전에는 `SELLFORM_GRAPH_RUNTIME=langgraph`를 실제 판매 상세페이지 생성 경로에 연결하지 않는다.
