# 코드리뷰: Sellform V2 LG-3 Commerce Planning Subgraph

검토일: 2026-08-07  
상태: **통과 — 원본 LG-3 완료 조건 충족**  
관련 계획: [LG-3 Commerce Planning Subgraph](../superpowers/plans/2026-08-07-sellform-v2-lg-3-commerce-planning-subgraph.md)

## 검토 범위

- `backend/src/agents/langgraph_runtime.py`
- `backend/src/agents/schemas.py`
- `backend/src/services/langgraph_commerce_planning_service.py`
- `backend/src/services/api_ready_generation_service.py`
- `backend/tests/test_lg3_commerce_planning_subgraph.py`

## 원본 완료 조건 검증

| 완료 조건 | 구현 근거 | 자동 검증 |
| --- | --- | --- |
| 네 에이전트가 이전 구조화 결과를 순서대로 사용 | `sales_strategy → page_planning → copywriting → visual_planning` LangGraph edge와 각 artifact 의존성 검사 | 실제 graph-run API의 node event 순서 |
| 승인 사실만 입력으로 사용 | snapshot ID/hash 검증, 원본 seller/freeform 입력 제거, LG-2 discovery 원문은 hash/version contract로만 전달 | seller-confirmed FactSnapshot fixture와 discovery 원문 비노출 검사 |
| 전략·섹션·카피·장면의 버전 스키마 고정 | `lg3-v1` schema와 후보/선택 근거, section purpose/fact IDs, copy provenance, typed `ScenePlanOutput` | 네 artifact Pydantic 검증 |
| 장면마다 목적·사실 ID·기준 자산·생성 방식 존재 | LG-3 ScenePlan projection이 빈 fact/reference 배열을 보정하고, 안전한 판매자 보유 기준 사진이 없으면 Visual Planning을 완료하지 않음 | 실제 graph run에서 모든 값의 비어 있지 않음 확인 |
| 미확인 수치·효능·경쟁 우월 표현 차단 | 숫자는 승인 사실의 전체 표면값과 함께 일치해야 하며, 경쟁사/최고/최상 등도 차단 | `5시간 연속 사용`, `경쟁사보다 뛰어난 업계 최고 제품` 차단 테스트 |
| 카피별 근거 연결 | `section_fact_ids`와 `copy_provenance`를 CopySet schema 안에 보존 | feature 카피의 fact ID 보존 확인 |
| 같은 snapshot/prompt mock 결과 재현 | 동적 timestamp와 이전 draft 의존성을 ScenePlan artifact에서 제거 | Sales Strategy와 Visual Planning 재실행 hash 비교 |
| 노드 재실행·사실 변경 시 하위 결과 무효화 | 이후 artifact/projection 제거 및 기존 `planning_draft`를 `stale`로 표시 | snapshot 교체 후 downstream artifact 제거와 모든 카드 stale 확인 |
| 기존 기획 화면 호환 | Visual Planning이 기존 `PlanningDraftSchema`로 materialize | `/api/v1/projects/{id}/planning-draft` 실제 GET 확인 |
| checkpoint 원문 미저장 | graph `commerce` state에는 artifact reference/hash만 저장 | state에 카피/사실 원문이 없는지 확인 |

## 회귀 검증

다음 명령을 실행했다.

```powershell
cd C:\page\backend
.\.venv\Scripts\python.exe -m pytest tests/test_lg3_commerce_planning_subgraph.py tests/test_lg2_discovery_subgraph.py tests/test_lg1_durable_graph_runtime.py tests/test_lg0_langgraph_runtime.py tests/test_lg0_legacy_characterization.py tests/test_11_agent_graph_contract.py tests/test_11_agent_node_contracts.py tests/test_agent_graph_contract.py tests/test_agent_run_api.py tests/test_source_collection_agent.py tests/test_reference_analysis_agent.py tests/test_v2_sprint3_evidence_board.py tests/test_ux2e0_api_ready_generation.py tests/test_planning_draft_service.py tests/test_planning_draft_approve_api.py -q
```

결과: **66 passed**. 기존 legacy 11-agent VisualPlan의 자유형 `scene_plan` 출력도 schema 호환 분기로 유지되어 LG-0 characterization regression이 통과한다.

## 결론

LG-3는 승인 사실 기반의 네 Commerce Planning 에이전트를 LangGraph에서 순차 실행하고, 안전한 카피·근거 연결·typed ScenePlan·기획 화면 adapter·재현 가능한 mock artifact·하위 결과 무효화를 제공한다. 안전한 판매자 보유 기준 사진이 없는 경우에는 장면을 근거 없이 완료 처리하지 않고 Visual Planning을 명시적으로 중단한다.
