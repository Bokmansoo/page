# Code Review - Sprint 51: Real LLM Text Pipeline

이 문서는 Sprint 51: Real LLM Text Pipeline 기획 사양의 구현 결과를 점검하고 승인하기 위한 코드 리뷰 문서입니다.

---

## 1. Review Summary

- **작업 상태**: 승인 (Approved)
- **작업 내용**:
  1. **실제 LLM Provider 어댑터 구축**: OpenAI, Gemini, Claude 3개 사의 API 규격 및 구조화 출력 모델(JSON Schema 강제 적용)을 포괄하는 Adapter 아키텍처 수립
  2. **Fallback 라우팅 구현**: 특정 API 호출 오류 시 다음 Provider로 전환해 주는 폴백 라우터 및 환경 설정 기반 팩토리 함수 제공
  3. **프롬프트 융합 체인 구축**: `PromptRegistry`를 사용해 마크다운 프롬프트를 융합하고, 이전 단계 결과(JSON)를 순차 피딩하는 체인 컨텍스트 수립
  4. **웹 실행 경로 API 제공**: `POST /api/agent-runs/{id}/run` 경로를 통해 에이전트 리얼 연산을 유발하고 완료 상태를 DB에 저장
  5. **동적 상세페이지 조립**: 최종 생성된 카피 및 섹션 구조를 토대로 `page_assembly`를 동적으로 조립하는 빌더 로직 개발
- **검증 여부**: Sprint 51 provider/통합 계약 테스트 12건과 관련 백엔드 회귀 테스트 51건을 외부 API 호출 없이 통과했습니다. 프론트 빌드 및 Mock 모드 E2E 검증도 통과했습니다.

---

## 2. Detailed Verification

### [1] Provider 어댑터 및 Fallback 라우팅
- **위치**: `backend/src/services/provider_adapters.py` & `backend/src/services/llm_router.py`
- **구현 결과**:
  - `OpenAITextProvider`: `beta.chat.completions.parse` 에 Pydantic 모델을 얹어 JSON 구조를 보장받습니다.
  - `GeminiTextProvider`: `response_schema` 에 JSON 스키마를 지정하여 구조적 엄밀함을 만족시킵니다.
  - `ClaudeTextProvider`: Pydantic의 `.model_json_schema()` 를 `tool`로 바인딩하여 안전한 JSON 출력을 실현합니다.
  - `FallbackTextProvider`: Provider 목록을 순회하며 예외 발생 시 다음 어댑터를 자동 격발합니다.
  - `get_text_provider_by_settings()`: 설정에 의거해 프로바이더 우선순위 순으로 dynamic fallback chain을 반환합니다.
  - 텍스트 파이프라인 전용 `SELLFORM_TEXT_LLM_*` provider/model 설정을 사용하며 기존 팩트 추출 라우터 설정과 분리했습니다.

### [2] 마크다운 프롬프트 연동 및 Context Chaining
- **위치**: `backend/src/agents/graph.py`
- **구현 결과**:
  - `PromptRegistry`를 이용하여 `system/sellform_agent_base` 와 `agents/` 폴더 내 마크다운 템플릿 프롬프트를 런타임에 동적으로 로드합니다.
  - 상품 입력과 검증된 상품 이해 결과를 이후 전략, 페이지 계획, 카피, 비주얼 단계에 누적 전달합니다.
  - 파일 부재 시 FileNotFoundError 가 정상 격발되도록 처리했습니다.

### [3] 동적 page_assembly 조립
- **위치**: `backend/src/agents/graph.py`
- **구현 결과**:
  - LLM으로 얻어낸 `copy_set`과 `page_plan.sections`를 정렬 기준 삼아 동적으로 `page_assembly` 목록을 조립합니다.
  - 조립 과정에서 섹션 내부의 copy 항목을 HTML이 아닌 본연의 title, body 구조에 정합하게 얹었습니다.
  - 검증되지 않은 KC, 정품, 경쟁 상품 비교 문구를 조립기에서 하드코딩하지 않으며 최종 조립본까지 포함해 QA를 실행합니다.

### [4] 웹 실행 경로 `/run` API 및 서비스 연동
- **위치**: `backend/src/api/agent_runs.py` & `backend/src/services/agent_run_service.py`
- **구현 결과**:
  - `POST /api/agent-runs/{id}/run` 엔드포인트가 연동되어 Workspace ID 권한 대조를 통과한 뒤 `AgentRunService.run_real_text`를 호출합니다.
  - DB 영속화 시 outputs, current_stage, status="completed"로 정상 전이 및 완료 일시가 저장됩니다.
  - 실행 환경의 Mock/Real mode, provider trace, token usage 및 산출 가능한 비용 정보를 함께 저장합니다.

---

## 3. Test Cases executed

### 1) Sprint 51 Provider/Contract Tests (12 Passed)
- `test_product_understanding_schema_requires_facts`: Pydantic 필수 팩트 필드 유효성 검증
- `test_sales_strategy_schema_has_recommended_direction`: 마케팅 세일즈 방향 정의 스키마 검증
- `test_real_text_graph_uses_provider_without_image_generation`: 에이전트 real_text 모듈 전체 통합 구동 검증 (동적 page_assembly 타이틀 노출 여부 포함)
- `test_run_real_api_endpoint`: FastAPI TestClient 기반 `/run` API 연동 호출 및 DB 상태 전이 검증
- `test_mock_text_provider_uses_requested_product_name`: Mock 결과가 입력 상품을 유지하는지 검증
- `test_text_provider_factory_uses_text_pipeline_settings`: GPT → Gemini → Claude 설정 체인 검증
- OpenAI, Gemini, Claude SDK 응답 파싱은 네트워크를 사용하지 않는 가짜 SDK 응답으로 검증

### 2) Related Backend Regression Suite (51 Passed)
- provider, real text graph, 기존 LLM router, facts, AgentRun API, prompt registry, graph/state/mode, Mock 생성 흐름을 함께 검증했습니다.

### 3) Frontend Verification
- `npm.cmd run build`: 성공
- `npm.cmd run test:e2e -- --grep "mock mode creates"`: 1 passed
- 화면은 `/run` 단일 경로를 호출하고 서버의 `SELLFORM_GENERATION_MODE`가 Mock/Real provider를 선택합니다.
- 실제 외부 LLM API와 유료 크레딧은 검증 과정에서 사용하지 않았습니다.

---

## 4. Review Verdict

**승인 (Approved)**: 기획서에서 명시한 사양들을 하위 호환성 이슈 없이 모두 준수하였으며, 백엔드 테스트 및 프론트 E2E Playwright 검증이 모두 완벽하게 통과되었음을 검증했습니다.
