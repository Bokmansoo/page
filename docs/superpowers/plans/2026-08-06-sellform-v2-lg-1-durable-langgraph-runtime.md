# Sellform V2 LG-1: Durable LangGraph Runtime 구현 계획

작성일: 2026-08-06  
상태: **구현 완료**  
상위 로드맵: [LangGraph 전환 Sprint 로드맵](./2026-08-06-sellform-v2-langgraph-migration-roadmap.md)

## 목표

기존 판매 상세페이지 생성 경로를 바꾸지 않은 채, `AgentRun.id`를 LangGraph `thread_id`로 사용하는 PostgreSQL 기반 실행·복구·운영 projection 기반을 만든다.

## 완료 조건

| 조건 | 구현 방법 | 검증 |
| --- | --- | --- |
| JSON 직렬화 가능 상태 | `SellformGraphState`는 ID, 승인 입력, 상태, 이벤트만 보관 | 입력의 비밀값 제거 테스트 |
| 실제 durable graph | `bootstrap_run → lg1_test_node → finalize_run` `StateGraph` | 3개 node 실행·history 테스트 |
| PostgreSQL checkpointer | `PostgresSaver` factory와 psycopg 3 binary 의존성 | 중단 후 별도 DB 연결에서 같은 thread 재개 |
| thread 계약 | `graph_thread_id == AgentRun.id` | API projection 테스트 |
| 운영 projection | graph node event만 `current_stage`를 변경하고 `AgentRunStep` upsert | 단계·상태·출력 검증 |
| start/get/history/cancel/resume 계약 | `/api/v1/graph-runs/{run_id}/...` | 실패한 run의 같은 checkpoint resume 테스트 |
| 멱등 시작 | 실행 중·완료된 같은 run을 다시 시작해도 새 step/thread 없음 | 실제 동시 start 테스트 |
| 기존 경로 보존 | `SELLFORM_GRAPH_RUNTIME=legacy` 기본값 유지 | LG-0/legacy 회귀 테스트 |

## 구현 범위

- PostgreSQL URL 검증 및 checkpointer lifecycle factory
- `agent_runs.graph_thread_id`, `agent_runs.graph_checkpoint_id`의 호환 스키마 추가
- 기존 `AgentRun`/`AgentRunStep`을 graph event로 투영하는 service
- graph run의 시작·조회·history·취소·resume API
- 실제 DB 재연결·중단 지점 재개와 실패 projection 복구 테스트

## 의도적으로 포함하지 않는 항목

- 실제 11개 도메인 에이전트의 LangGraph node 전환: LG-2 ~ LG-6
- 사용자 승인 interrupt와 `Command(resume=...)`: LG-4
- 기존 상세페이지 생성 버튼을 graph-run API로 교체: LG-8

LG-1의 `resume`은 사람 승인 interrupt를 재개하는 기능은 아니다. 다만 프로세스·projection 실패 뒤에는 동일 checkpoint에서 다음 노드부터 실제로 재개한다. 사람 승인용 `Command(resume=...)` payload는 LG-4 범위다.
