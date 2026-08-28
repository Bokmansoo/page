# Sellform V2 LG-2: Discovery Subgraph 구현 계획

작성일: 2026-08-07  
상태: **구현 및 통합 검증 완료**  
상위 로드맵: [LangGraph 전환 Sprint 로드맵](./2026-08-06-sellform-v2-langgraph-migration-roadmap.md)

## 목표

기존 상세페이지 생성의 첫 네 에이전트(Input Router, Source Collection,
Product Understanding, Reference Analysis)를 실제 `StateGraph` 노드로
운영한다. 기존 에이전트 스키마와 프롬프트·증거 보드·ProductBrief 계약은
유지한다.

## 구현 계약

| 요구 사항 | 구현 방식 |
| --- | --- |
| 네 에이전트 노드 | `build_lg2_compiled_graph()`가 네 노드와 URL 조건 분기를 등록한다. |
| 기존 스키마 | 각 노드는 기존 Pydantic 결과를 검증하고, 결과 원문은 `AgentRun.outputs_json.langgraph_discovery_artifacts`에 저장한다. |
| 체크포인트 안전성 | graph state에는 라우팅 결과, asset/capture ID, FactSnapshot ID/hash만 둔다. fact/evidence/OCR 원문과 ORM 객체는 넣지 않는다. |
| 프롬프트 유지 | 기존 네 프롬프트의 해시를 artifact 메타데이터에 기록한다. Product Understanding의 real 모드는 기존 system/node prompt와 provider router를 실제 호출한다. |
| 자산/OCR | Source Collection은 `run_project_asset_inspections`와 asset-understanding blocker 서비스를 호출한다. |
| 증거 보드 | Product Understanding은 `refresh_evidence_board`, `fact_board_blockers`, `approved_fact_snapshot`을 통해 승인 사실만 `verified_facts`로 넣는다. |
| URL 없음 | Reference Analysis는 `reference_analysis_skipped` 경로로 가며 `no_reference_url`을 기록한다. |
| URL 수집 실패 | 직접 업로드 자산이 있으면 `continue_with_direct_uploads`로 계속 진행한다. URL 존재 시 Reference Analysis는 실행되지만 `collection_failed`를 정직하게 기록한다. |
| ProductBrief 호환 | `compatible_product_brief()`가 기존 `build_generation_plan()`의 canonical ProductBrief와 네 에이전트 결과를 함께 제공한다. |
| DB 내구성 | 그래프 노드는 request-scoped DB session을 ContextVar로 공유한다. Session은 graph state에 넣지 않으며 node artifact/fact snapshot은 checkpoint보다 먼저 저장되고, projection 누락은 기존 history replay가 복구한다. |

## 그래프

```text
START → bootstrap_run → input_router → source_collection → product_understanding
                                                          ├─ URL 있음 → reference_analysis → finalize_run
                                                          └─ URL 없음 → reference_analysis_skipped → finalize_run
```

`reference_analysis_skipped`는 구현상 별도 노드지만, 운영 event와
`AgentRunStep`에는 기존 에이전트 계약대로 `reference_analysis` / `skipped`로 남는다.

## 완료 조건과 통합 검증

- 네 기존 에이전트가 실제 StateGraph 노드로 실행된다.
- URL 없음, URL 수집 실패+직접 업로드, real provider의 schema/prompt 계약을 각각 실제 graph/API 경로로 검사한다.
- 승인되지 않은 provider 추론값은 `verified_facts`로 승격되지 않는다.
- checkpoint에 raw fact/evidence가 없는지 검사한다.
- 기존 evidence board와 `build_generation_plan()` ProductBrief가 같은 실행 데이터로 동작하는지 검사한다.
- LG-0/LG-1, 기존 11-agent 계약, AgentRun API, evidence-board, API-ready generation 회귀 테스트를 함께 통과한다.

검증 명령:

```powershell
cd C:\page\backend
.\.venv\Scripts\python.exe -m pytest tests/test_lg2_discovery_subgraph.py tests/test_lg1_durable_graph_runtime.py tests/test_lg0_langgraph_runtime.py tests/test_lg0_legacy_characterization.py tests/test_11_agent_graph_contract.py tests/test_11_agent_node_contracts.py tests/test_agent_graph_contract.py tests/test_agent_run_api.py tests/test_source_collection_agent.py tests/test_reference_analysis_agent.py tests/test_v2_sprint3_evidence_board.py tests/test_ux2e0_api_ready_generation.py -q
```

결과: **55 passed**.

## 완료 판정 규칙

이 Sprint는 문서상 기능 목록만 구현했거나 mock만 통과한 상태를 완료로 보지 않는다.
위 통합 검증이 모두 통과하고, review 문서의 각 완료 조건에 코드 위치와 테스트 근거가 있을 때만 완료로 판정한다.
