# Sellform V2 LG-3: Commerce Planning Subgraph 구현 계획

작성일: 2026-08-07  
상태: **구현 및 통합 검증 완료**  
상위 로드맵: [LangGraph 전환 Sprint 로드맵](./2026-08-06-sellform-v2-langgraph-migration-roadmap.md)

## 목표

LG-2 Discovery의 승인 사실 스냅샷을 판매 가능한 상세페이지 기획으로
전환한다. 대상 에이전트는 Sales Strategy, Page Planning, Copywriting,
Visual Planning이며, 결과는 기존 기획 화면에서도 읽을 수 있어야 한다.

## 구현 계약

| 요구 사항 | 구현 방식 |
| --- | --- |
| 순차적 구조화 입력 | Sales Strategy는 LG-2 Discovery artifact와 승인 FactSnapshot을 읽고, 이후 세 노드는 바로 앞 planning artifact를 순서대로 읽는다. |
| 승인 사실만 사용 | snapshot ID/hash 검증 후 `facts_json`을 node-local로만 해제한다. Sales Strategy와 Copywriting에는 LG-2 discovery 원문을 전달하지 않고 artifact hash/version contract만 전달한다. state에는 ID/hash와 artifact hash만 남긴다. |
| 버전 artifact | 전략 후보/선택 근거, 페이지 섹션 purpose/fact IDs, 카피 provenance, typed ScenePlan을 포함한 네 결과를 `lg3-v1` schema로 검증해 `langgraph_commerce_planning_artifacts`에 저장한다. |
| 카피 안전성 | 금지 표현·미확인 숫자·효능·경쟁 우월 claim은 제거한다. 숫자는 승인 사실의 전체 표면값과 함께 일치할 때만 허용하고, 각 카피 필드의 사실 ID 또는 `narrative_non_claim` 분류를 output과 metadata에 남긴다. |
| ScenePlan 통합 | Visual Planning은 UX-2E generation plan을 typed ScenePlan으로 projection한다. 장면마다 objective, source_fact_ids, reference_asset_ids, generation_mode, requested_output이 비어 있지 않으며, 안전한 판매자 보유 기준 사진이 없으면 완료하지 않는다. |
| 기존 기획 화면 | Visual Planning 완료 시 기존 `ProductProject.planning_draft` schema로 read adapter를 저장한다. 기존 `/planning-draft` API와 화면이 새 초안을 그대로 읽는다. |
| 재현성 | mock 결과와 prompt hash·입력 hash를 artifact에 보관한다. 동적 시각과 이전 draft 결과를 artifact 입력에서 제외해, 같은 승인 snapshot/prompt의 Sales Strategy 및 Visual Planning 재실행은 같은 artifact hash를 만든다. |
| 무효화 | 노드를 재실행하거나 승인 FactSnapshot이 바뀌면 이후 commerce artifact/projection을 제거하고 기존 `planning_draft`를 `stale`로 표시한다. |

## 그래프

```text
LG-2 Discovery
  → sales_strategy
  → page_planning
  → copywriting
  → visual_planning
  → finalize_run
```

## 완료 조건과 검증

- 네 planning 에이전트가 실제 `StateGraph` 노드로 실행된다.
- graph checkpoint에 카피·사실 원문·장면 원문을 넣지 않는다.
- scene contract의 목적·사실 ID·기준 자산·생성 방식과 copy provenance를 실제 graph API 실행으로 확인한다.
- 동일 snapshot의 mock Sales Strategy 및 Visual Planning 재실행 artifact hash가 재현된다.
- snapshot 변경 또는 상위 노드 재실행 시 downstream artifact가 제거되고 planning draft가 stale 처리된다.
- 기존 planning-draft API가 LG-3가 만든 초안을 반환한다.

검증 명령:

```powershell
cd C:\page\backend
.\.venv\Scripts\python.exe -m pytest tests/test_lg3_commerce_planning_subgraph.py tests/test_lg2_discovery_subgraph.py tests/test_lg1_durable_graph_runtime.py tests/test_lg0_langgraph_runtime.py tests/test_lg0_legacy_characterization.py tests/test_11_agent_graph_contract.py tests/test_11_agent_node_contracts.py tests/test_agent_graph_contract.py tests/test_agent_run_api.py tests/test_source_collection_agent.py tests/test_reference_analysis_agent.py tests/test_v2_sprint3_evidence_board.py tests/test_ux2e0_api_ready_generation.py tests/test_planning_draft_service.py tests/test_planning_draft_approve_api.py -q
```

결과: **66 passed**.
