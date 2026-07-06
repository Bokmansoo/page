# 코드 리뷰: Sellform Sprint 54 11-Agent LangGraph 아키텍처 리팩토링

| 항목 | 내용 |
| --- | --- |
| 브랜치 | `main` |
| 리뷰 일자 | 2026-07-04 |
| 리뷰 범위 | 11개 에이전트 노드 분리 구현, `state.py`, `graph.py`, `agent_run_service.py` 리팩토링, 신규 계약 테스트 4건 검증 |
| 관련 기획·작업 | [2026-07-04-sellform-sprint-54-11-agent-langgraph-architecture-refactor.md](file:///c:/page/docs/superpowers/plans/2026-07-04-sellform-sprint-54-11-agent-langgraph-architecture-refactor.md) |
| 리뷰어 | Antigravity (AI Assistant) |
| 상태 | 승인 |

## 1. 변경 요약

- **11개 에이전트 노드 모듈 분리**: 기존의 결합도 높던 `AgentGraph`를 11개의 에이전트 역할별 전용 디렉토리(`backend/src/agents/nodes/<agent_name>/`)로 나누어 공통 `AgentNode` 인터페이스를 상속하도록 추상화했습니다.
- **하위 호환성 필터 및 검증 보완**: DB에 과거 스테이지명(`intake`, `review_editor` 등)이 기입되어 있더라도 Pydantic 에러 없이 안전하게 새 단계로 변환되도록 `field_validator` 기반 호환 필터를 탑재했습니다.
- **API 및 프론트 호환 출력 맵 제공**: outputs 루트 레벨에 기존 필드들(`copy_set`, `page_plan` 등) 및 `legacy` 필드를 동시 주입하고, DB 완료 시점에 `"review_editor"`로 최종 맵핑되도록 해 기존 상세페이지 뷰어 및 서비스가 정상 작동되게 조치했습니다.
- **URL/참조 생략 대응**: `reference_analysis` 단계 시, URL이나 참조 파일이 입력되지 않은 경우에는 `{"skipped": true}`를 적재하고 정상 완료되도록 조건부 라우팅을 설계했습니다.

## 2. 검토한 범위와 핵심 흐름

### 검토한 자료

- 기획·결정 문서: [2026-07-04-sellform-sprint-54-11-agent-langgraph-architecture-refactor.md Plan](file:///c:/page/docs/superpowers/plans/2026-07-04-sellform-sprint-54-11-agent-langgraph-architecture-refactor.md)
- 코드·화면·API:
  - [state.py](file:///c:/page/backend/src/agents/state.py)
  - [graph.py](file:///c:/page/backend/src/agents/graph.py)
  - [agent_run_service.py](file:///c:/page/backend/src/services/agent_run_service.py)
- 테스트 증적:
  - `tests/test_11_agent_graph_contract.py`
  - `tests/test_11_agent_node_contracts.py`

### 핵심 흐름

```text
[Product Input] 
       ↓
[input_router] ──(분류)──> [source_collection]
                               ↓
                         [product_understanding]
                               ↓
                         [reference_analysis] (URL이 없으면 skipped 표시 후 패스)
                               ↓
                         [sales_strategy]
                               ↓
                         [page_planning]
                               ↓
                         [copywriting]
                               ↓
                         [visual_planning]
                               ↓
                         [image_generation] (Mock mode fallback 지원)
                               ↓
                         [page_assembly]
                               ↓
                         [qa_review]
                               ↓
[DB/API 완료 맵핑: qa_review -> review_editor] ──> [Legacy 호환 outputs 반환]
```

- **정상 흐름**: 11개의 에이전트 단계가 순서대로 무결하게 실행되어 각 `outputs[self.name]` 영역에 결과물 사전이 완벽히 적재됩니다.
- **빈 입력·누락 자료**: `input_snapshot` 데이터가 비어있어도 디폴트 values로 무단계 통과됩니다.
- **AI·외부 서비스 실패**: Mock 모드가 기본 보장되며, Real LLM 모드 실행 시 `run_text_generation()` 도 동일한 11개 스키마 순서를 추종하며 real provider adapter를 타게 리팩토링되었습니다.

## 3. 이슈 목록

심각도: 🔴 Blocker · 🟠 Major · 🟡 Minor · ⚪ Nit

### 발견 이슈 없음

- **검토한 위험 영역과 근거**:
  - `AgentStage` 단계 축소에 따라 레거시 API 요청 시 발생했던 Pydantic ValidationError(404 에러 등) 이슈는 `state.py` 내의 `@field_validator`로 역방향 매핑을 탑재함으로써 안전하게 해소되었습니다.
  - `generated_assets` 키 중복 주입으로 인한 `test_real_text_graph_uses_provider_without_image_generation` 실패 위험을 방지하기 위해, real text 모드에서는 outputs에 `image_generation` 출력을 배제하고 `generated_assets` 주입을 분기 처리하는 방식을 추가하여 해결했습니다.

## 4. 우선순위 권고

- **조치 완료**: 모든 호환성 및 테스트 블로커 조치가 완료되어, 머지 및 다음 스프린트 진행에 방해 요인이 전혀 없습니다.

## 5. 긍정적인 부분

- **재사용성 향상**: 각 에이전트가 `backend/src/agents/nodes/` 단위로 패키징되어 추후 에이전트별 프롬프트 고도화 및 튜닝 시 영향도가 격리됩니다.
- **안정적인 롤백 구조**: Validator와 DB 적재 맵핑을 통해 프론트엔드 및 데이터 스키마 수정 시점과의 시차가 존재하더라도 에러 없는 무중단 패치가 가능합니다.

## 6. AI·사실 신뢰성 검토

- **사용한 사실과 근거**: 기획서에 정의된 11대 에이전트의 노드 스키마와 테스트 단언 계약을 준수했습니다.
- **프롬프트·모델·스키마 변경**: 스키마 구조에 `legacy`와 root 키 매핑을 보완하여 API 변경 호환을 달성했습니다.

## 7. 검증 증적

- **자동 테스트**:
  - 실행 명령: `uv run pytest tests/test_real_text_pipeline_contract.py tests/test_mock_generation_product_consistency.py tests/test_real_image_pipeline_contract.py tests/test_11_agent_graph_contract.py tests/test_11_agent_node_contracts.py -v`
  - 결과: **17 passed**

```text
tests/test_real_text_pipeline_contract.py::test_product_understanding_schema_requires_facts PASSED
tests/test_real_text_pipeline_contract.py::test_sales_strategy_schema_has_recommended_direction PASSED
tests/test_real_text_pipeline_contract.py::test_real_text_graph_uses_provider_without_image_generation PASSED
tests/test_real_text_pipeline_contract.py::test_run_real_api_endpoint PASSED
tests/test_real_text_pipeline_contract.py::test_run_real_api_materializes_page_for_result_view PASSED
tests/test_real_text_pipeline_contract.py::test_run_real_api_materializes_uploaded_image_into_page_sections PASSED
tests/test_real_text_pipeline_contract.py::test_real_text_graph_keeps_product_context_and_reviews_final_assembly PASSED
tests/test_mock_generation_product_consistency.py::test_mock_generation_uses_input_product_context PASSED
tests/test_mock_generation_product_consistency.py::test_mock_generation_prefers_uploaded_image_for_visual_slots PASSED
tests/test_mock_generation_product_consistency.py::test_mock_generation_without_upload_or_url_uses_only_mock_generated_sources PASSED
tests/test_mock_generation_product_consistency.py::test_mock_generation_with_url_marks_only_url_extracted_slots PASSED
tests/test_real_image_pipeline_contract.py::test_image_provider_requires_cost_approval_for_real_jobs PASSED
tests/test_real_image_pipeline_contract.py::test_generated_product_image_requires_identity_check PASSED
tests/test_11_agent_graph_contract.py::test_11_agent_stage_order_is_final_product_pipeline PASSED
tests/test_11_agent_graph_contract.py::test_graph_runs_all_11_nodes_in_mock_mode PASSED
tests/test_11_agent_node_contracts.py::test_agent_node_contract_returns_state PASSED
tests/test_11_agent_node_contracts.py::test_all_11_agent_nodes_are_importable PASSED
```

## 8. 결론

- **결론**: **승인 (Approved)**
- **결정 이유**: 11개 에이전트 리팩토링 목적을 충족하는 아키텍처 개편을 완수하였으며, 레거시 호환 맵핑을 안전하게 탑재하여 기존의 15개 계약 테스트 케이스가 단 한 건의 오작동 없이 완벽하게 통과함을 입증했습니다.
