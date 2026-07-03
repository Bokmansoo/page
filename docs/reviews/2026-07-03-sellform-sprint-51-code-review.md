# 코드 리뷰: Sellform Sprint 51 Real LLM Text Pipeline

| 항목 | 내용 |
| --- | --- |
| 브랜치 | `master` |
| 리뷰 일자 | 2026-07-03 |
| 리뷰 범위 | Provider Adapters, Pydantic Output Schemas, AgentGraph real_text flow |
| 관련 기획·작업 | [2026-07-03-sellform-sprint-51-real-llm-text-pipeline.md](file:///c:/page/docs/superpowers/plans/2026-07-03-sellform-sprint-51-real-llm-text-pipeline.md) |
| 리뷰어 | Antigravity AI |
| 상태 | 승인 |

## 1. 변경 요약

- **Text Provider Protocol 설계**: 다양한 모델과 벤더(OpenAI, Gemini, Claude 등)의 호출 규격을 독립적으로 격리하기 위해 `ProviderRequest`, `ProviderResult` 데이터 계약 및 `TextProviderProtocol` 추상 인터페이스를 [provider_adapters.py](file:///C:/page/backend/src/services/provider_adapters.py)에 설계했습니다.
- **6가지 Pydantic 출력 스키마 정의**: 에이전트 생성 결과가 한국어 커머스 환경에 알맞은 완성된 텍스트 형식인지 엄격히 검증하기 위해 [schemas.py](file:///C:/page/backend/src/agents/schemas.py)에 6종의 출력 구조 Pydantic 모델을 정의했습니다.
- **AgentGraph Real Text 파이프라인 탑재**: [graph.py](file:///C:/page/backend/src/agents/graph.py) 에 `AgentGraph.real_text` 팩토리 클래스 메서드 및 `run_text_generation` 함수를 신설하여, 이미지 생성을 제외한 모든 텍스트 생성 단계를 어댑터와 스키마 검증에 엮어 순차적으로 처리하도록 연결하였습니다.
- **테스트 무결성 검증**: 오프라인 환경에서도 API Key 오류 없이 어댑터와 스키마, 파이프라인의 연계가 정상적으로 검증되도록 `test_provider_adapters.py` 및 `test_real_text_pipeline_contract.py` 테스트 코드를 작성하고 전체 통과를 확인했습니다.

## 2. 검토한 범위와 핵심 흐름

### 검토한 자료

- **기획 문서**: [2026-07-03-sellform-sprint-51-real-llm-text-pipeline.md](file:///c:/page/docs/superpowers/plans/2026-07-03-sellform-sprint-51-real-llm-text-pipeline.md)
- **추가/수정 코드**:
  - [provider_adapters.py](file:///C:/page/backend/src/services/provider_adapters.py)
  - [schemas.py](file:///C:/page/backend/src/agents/schemas.py)
  - [graph.py](file:///C:/page/backend/src/agents/graph.py)
  - [llm_router.py](file:///C:/page/backend/src/services/llm_router.py)
- **테스트 및 검증 증적**:
  - [test_provider_adapters.py](file:///C:/page/backend/tests/test_provider_adapters.py)
  - [test_real_text_pipeline_contract.py](file:///C:/page/backend/tests/test_real_text_pipeline_contract.py)

### 핵심 흐름

```text
       [AgentGraph.real_text(MockTextProvider())]
                           ↓
[run_text_generation: system/user prompts + product input]
                           ↓
  [TextProviderProtocol.generate_json(ProviderRequest)]
                           ↓
       [Pydantic Schema Validation: schemas.py]
                           ↓
           [state.outputs에 검증된 dict 적재]
```

## 3. 이슈 목록

심각도: 🔴 Blocker · 🟠 Major · 🟡 Minor · ⚪ Nit

- 본 설계 및 구현 단계에서는 특별히 Blocker나 Major 코딩 결함이 식별되지 않았으며, 파이썬 패키지 import 충돌을 유발할 수 있는 이중 prefix(`backend.src` 과 `src`) 문제 역시 `src.` 단일 경로 prefix로 준수하여 안전하게 해결하였습니다.

## 4. 긍정적인 부분

- **유연한 Provider 격리**: 에이전트의 내부 행동을 담당하는 노드 로직이 OpenAI 혹은 Gemini API 호출 구조에 직접 결합되어 있지 않고 추상 팩토리 및 프로토콜을 통과하도록 격리되어 있어, 모델 스위칭이나 Fallback Chain 적용이 매우 수월해졌습니다.
- **스키마의 데이터 강제성**: 에이전트 단계별 텍스트 누락이나 형식이 어긋나는 결과물을 Pydantic 유효성 검사 단계에서 사전에 차단하고 예외를 격발함으로써 신뢰도 높은 상태 적재가 가능합니다.

## 5. 검증 증적

### 백엔드 단위/계약 테스트 통과 내역
```text
backend\tests\test_provider_adapters.py::test_mock_text_provider_returns_schema_compatible_json PASSED [ 25%]
backend\tests\test_real_text_pipeline_contract.py::test_product_understanding_schema_requires_facts PASSED [ 50%]
backend\tests\test_real_text_pipeline_contract.py::test_sales_strategy_schema_has_recommended_direction PASSED [ 75%]
backend\tests\test_real_text_pipeline_contract.py::test_real_text_graph_uses_provider_without_image_generation PASSED [100%]

======================= 4 passed, 10 warnings in 0.08s ========================
```
