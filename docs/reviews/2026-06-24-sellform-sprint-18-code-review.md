# Sellform Sprint 18 Code Review

**Sprint Goal:** 단일 OpenAI API 연동에서 다중 Provider 순차 폴백 LLM 라우터 체인을 구축하고, SQLite 및 PostgreSQL 데이터베이스 이기종 호환성을 수립합니다.

---

## 1. 주요 변경 파일 목록

- `backend/src/config.py` (LLM 라우터 설정 상수 추가 및 하위 호환 effective_openai_model property 제공)
- `backend/src/db/models.py` (ProductFact DB 모델에 `provider` 및 `model_name` 메타데이터 컬럼 추가)
- `backend/src/api/facts.py` (FactResponseSchema 스키마 갱신 및 LLMRouter 호출/저장 연동)
- `backend/src/services/llm_router.py` (LLMRouter 구현 - openai -> google -> deterministic 폴백 체인 구축)
- `backend/tests/test_llm_router.py` (단위 테스트 작성)
- `backend/tests/test_facts.py` (통합 테스트 람다 모킹 오류 수정 및 호환성 보강)
- `docker-compose.yml` (PostgreSQL 호스트 포트를 5434로 매핑하여 포트 충돌 우회)
- `docs/runbooks/2026-06-24-sellform-local-server-runbook.md` (PostgreSQL 실행 방법 가이드 추가)

---

## 2. 코드 구조 검토 및 분석

### 2.1 LLMRouter (`llm_router.py`)
- Pydantic Settings에서 `SELLFORM_LLM_DEFAULT_PROVIDER` 및 폴백 지정자들을 읽어 리스트로 루프를 돌리는 디자인을 채택했습니다.
- 각 어댑터 호출을 개별 try-except로 가두어 실패 시 예외를 전파하지 않고 `failed_sources` 메타데이터 리스트에만 누적함으로써, 외부 API 장애로 인한 API 전체 장애 파급을 완벽하게 차단했습니다.
- OpenAI 성공 시 Gemini를 호출하지 않는 순차적 short-circuit 구조가 바르게 구현되었습니다.
- **최적화:** API 키가 없는 경우 이를 실제 런타임 '에러'가 아닌 '비활성화(Skipped)'로 판단하여 `continue`로 건너뜁니다. 이를 통해 `failed_sources`에 불필요한 API Key 누락 로그가 남는 문제를 방지했습니다.

### 2.2 API 연동부 (`facts.py`)
- `_extract_ai_fact_candidates` 내부에서 `LLMRouter().extract_facts(raw_text)`를 호출하여 candidates와 failed_sources, 그리고 결정된 provider/model을 통합하여 리턴하도록 수정했습니다.
- 만약 최종 provider가 `deterministic` 일 경우에는 이미지 OCR 자산 맵핑 무결성(source_asset_id 연결 호환성) 유지를 위해 기존처럼 `extract_fact_candidates(collection.sources)`를 전면 사용하도록 함으로써 기존 코드와의 하위 호환성을 완벽하게 지켰습니다.
- **하위 호환성:** AI 호출 도중 실제로 런타임 실패가 난 경우에만 `ai_adapter_failed` 오류 정보를 `failed_sources`에 추가하도록 필터링을 개선하여, API 키가 존재하지 않는 클린 상태에서의 불필요한 오류 리포팅 문제를 방지했습니다.
- 생성된 팩트 카드를 DB 테이블에 인서트할 때 `provider` 와 `model_name` 을 함께 지정하여 감사 및 추적을 용이하게 했습니다.
- **테스트 환경 격리:** `conftest.py`에서 테스트 실행 전 기본적으로 API 키들을 `None`으로 소거하도록 하여, 로컬 개발 환경의 `.env` 파일 유무와 관계없이 테스트 중 실제 API 외부 호출이 발생하지 않도록 안정성을 극대화했습니다.

### 2.3 DB 스키마 갱신 (`models.py` 및 Pydantic 스키마)
- `ProductFact` 모델 클래스에 `provider` 및 `model_name` 필드를 적절한 길이 제한을 지닌 SQL Column으로 추가했습니다.
- `FactResponseSchema` 에도 동일하게 메타데이터를 추가함으로써 프론트엔드가 이를 온전히 인지하도록 설계했습니다.

---

## 3. 종합 평가

- **유연성 (Flexibility):** 복잡한 에이전트 오케스트레이션 프레임워크(LangGraph 등)를 도입하기 전 단계에서, 가볍고 성능 오버헤드가 적은 순수 서비스 구현 기반의 LLM 라우터 체인을 영리하게 구축했습니다.
- **안정성 (Stability):** 람다 가변 인자 모킹을 통해 pytest 환경 하에서 monkeypatch 모킹 무결성을 지켰으며, 5432 포트 충돌 회피(5434 포트 맵핑)를 통해 로컬 PostgreSQL 테스트의 신뢰성을 달성했습니다.
- **운영 준비성 (Operational Readiness):** SQLite와 PostgreSQL 데이터베이스가 완벽하게 양립 작동함을 실제 Smoke Test로 입증하여, 구독형 멀티테넌트 환경 전환을 위한 초석을 닦았습니다.

---

## 4. 후속 정리 리뷰 - 설정 네이밍 정리 (2026-06-25)

### 변경 요약

- 공개 환경 변수 네이밍을 `SELLFORM_*` 기준으로 정리했습니다.
- `backend/src/config.py`에서 중복 선언되어 있던 `FACTORY_LLM_*` 직접 필드를 제거했습니다.
- 기존 Sprint-era 환경과의 호환을 위해 `FACTORY_LLM_*` 값은 `AliasChoices`를 통해 계속 읽을 수 있게 유지했습니다.
- `.env.example`에서 `FACTORY_LLM_*` 예시와 중복 API key 블록을 제거했습니다.
- `backend/src/api/facts.py`의 미사용 `OpenAIAdapter` import를 제거했습니다.
- `docs/decisions/2026-06-24-sellform-llm-router-and-db-runtime.md`와 Sprint 18 실행계획 문서의 설정 설명을 `SELLFORM_*` 기준으로 갱신했습니다.

### 리뷰 결과

- 기능상 회귀는 발견되지 않았습니다.
- 새 공개 설정명은 `SELLFORM_LLM_*`, `SELLFORM_RAG_*`로 통일되었습니다.
- 기존 `FACTORY_LLM_*`, `FACTORY_RAG_*` 환경 변수는 하위 호환 alias로만 유지됩니다.

### 추가 주의

- 로컬 `.env`는 `.gitignore`에 포함되어 있으나 실제 API 키가 들어갈 수 있으므로 화면 공유, 로그, 리뷰 문서에 노출되지 않도록 주의해야 합니다.
