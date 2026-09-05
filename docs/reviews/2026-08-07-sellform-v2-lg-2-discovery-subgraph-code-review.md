# 코드리뷰: Sellform V2 LG-2 Discovery Subgraph

검토일: 2026-08-07  
상태: **통과 — LG-2 완료 조건 충족**  
관련 계획: [LG-2 Discovery Subgraph](../superpowers/plans/2026-08-07-sellform-v2-lg-2-discovery-subgraph.md)

## 최초 검토에서 확인된 미구현 사항

초기 구현은 노드 등록과 fake 기반 테스트는 있었지만, 다음 계약이 실제 실행 경로에 연결되지 않아 완료로 볼 수 없었다.

1. Input Router/Source Collection의 반환값이 기존 Pydantic 스키마와 맞지 않았다.
2. Source Collection이 OCR·asset-understanding 서비스가 아닌 단순 DB 조회에 머물렀다.
3. Product Understanding이 evidence board/FactSnapshot을 생성·참조하지 않았고, ProductBrief adapter도 없었다.
4. real provider의 기존 prompt/schema 계약을 실행으로 검증하지 않았다.
5. 서로 다른 DB 세션의 artifact 저장과 graph projection이 충돌할 수 있었다.

아래 수정과 실제 API/graph 통합 테스트로 모두 보완했다.

## 계획 대비 증거

| 완료 조건 | 구현 근거 | 검증 근거 | 결과 |
| --- | --- | --- | --- |
| 네 Discovery 에이전트가 StateGraph 노드 | `backend/src/agents/langgraph_runtime.py`의 `build_lg2_compiled_graph`와 네 `run_delta()` | graph-run API 실행에서 네 `AgentRunStep` 확인 | 통과 |
| 기존 결과 스키마 유지 | `langgraph_discovery_service.py`가 InputRouter/SourceCollection/ProductUnderstanding/ReferenceAnalysis schema를 검증 후 artifact 저장 | `test_lg2_discovery_subgraph.py`가 네 artifact를 기존 스키마로 재검증 | 통과 |
| URL 없음은 Reference Analysis skipped | `_lg2_has_reference_url`, `run_reference_analysis_skip` | 실제 graph API에서 `no_reference_url`/skipped 확인 | 통과 |
| 링크 실패 후 직접 업로드 진행 | `collect_discovery_sources`의 `collection_failures`와 `continue_with_direct_uploads` | 실패 SourceCapture + seller-owned Asset 통합 테스트 | 통과 |
| 누락 입력/수집 실패는 routing decision | `input_routing_decision`, source routing fields | 예외가 아닌 명시적 decision을 검사 | 통과 |
| OCR/asset 이해와 fact board 사용 | `run_project_asset_inspections`, `project_asset_understanding_blockers`, `refresh_evidence_board`, `approved_fact_snapshot` 호출 | 실제 graph API + fact fixture로 snapshot과 artifact 확인 | 통과 |
| 승인 사실 외 verified fact 금지 | `_product_output`이 provider 결과의 `verified_facts`를 승인 snapshot 값으로 대체 | fake real-provider가 임의 사실을 반환해도 승인 사실만 남는지 검사 | 통과 |
| 사실 원문은 checkpoint에 미저장 | state에는 `fact_snapshot.id/hash`만 반환 | state의 raw fact/evidence 미포함 검사 | 통과 |
| mock/real 동일 schema 및 기존 prompt 사용 | real path가 `ProviderRequest`에 기존 system/node prompt를 사용 | mock/real output schema keys와 prompt 내용 검사 | 통과 |
| ProductBrief/evidence board 호환 | `compatible_product_brief()` → 기존 `build_generation_plan()` | graph 실행 뒤 canonical ProductBrief와 Discovery artifact가 같은 승인 사실을 읽는지 검사 | 통과 |
| DB 저장 충돌·복구 | `langgraph_execution_session` ContextVar로 request session 공유, artifact/snapshot 선저장 + history replay | SQLite 기반 실제 graph API 통합 테스트 통과 | 통과 |

## 회귀 테스트

```powershell
cd C:\page\backend
.\.venv\Scripts\python.exe -m pytest tests/test_lg2_discovery_subgraph.py tests/test_lg1_durable_graph_runtime.py tests/test_lg0_langgraph_runtime.py tests/test_lg0_legacy_characterization.py tests/test_11_agent_graph_contract.py tests/test_11_agent_node_contracts.py tests/test_agent_graph_contract.py tests/test_agent_run_api.py tests/test_source_collection_agent.py tests/test_reference_analysis_agent.py tests/test_v2_sprint3_evidence_board.py tests/test_ux2e0_api_ready_generation.py -q
```

결과: **55 passed**. 경고는 기존 FastAPI/Starlette, Google SDK, Pydantic 및 `datetime.utcnow` deprecation 경고이며 테스트 실패는 없다.

## 결론

LG-2는 이제 원래 기획의 상태 계약, 도메인 서비스 연결, ProductBrief/evidence-board 호환, URL 분기, mock/real schema 계약을 실제 경로로 검증한다. 다음 LG-3으로 진행할 수 있다.
