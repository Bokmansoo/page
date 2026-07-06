# Sellform Sprint 16 Real AI Fact Extraction Test Log

본 문서는 Sprint 16 (Real AI Fact Extraction)의 환경 변수 갱신 및 API 키 연동 검증을 위해 백엔드 Pytest 테스트를 수행한 결과 기록 로그입니다.

---

## 1. 백엔드 Pytest 자동화 테스트 결과

### 1.1 AI Adapter 단위 테스트 (`test_ai_adapter.py`)

단위 테스트를 통해 각 AI Provider별(OpenAI, Anthropic, Gemini) 팩트 추출 어댑터가 올바르게 구조화 데이터(Pydantic Schema)를 생성하고 예외에 적절히 응답하는지 검증했습니다.

```powershell
uv run --project backend pytest backend/tests/test_ai_adapter.py -q
```

**테스트 출력 로그:**
```text
.....                                                                    [100%]
5 passed, 10 warnings in 0.07s
```

### 1.2 AI 사실 추출 API 통합 테스트 (`test_facts.py`)

통합 테스트를 통해 다음 시나리오를 검증했습니다:
1. `test_auto_extract_creates_reviewable_fact_candidates_from_manual_text`: API 키 미설정 시 mock fallback 동작 검증 (API 키 부재 시 자동 확인되지 않고 `unknown` 또는 `needs_revision` 상태로 fallback 수집 안내가 포함되어 저장되는 흐름).
2. `test_auto_extract_uses_url_source_text_for_fact_candidates` & `test_auto_extract_uses_image_ocr_text_for_fact_candidates`: 실제 AI 어댑터를 호출하여 팩트가 생성되고 올바르게 매핑되는 통합 흐름 검증.

```powershell
uv run --project backend pytest backend/tests/test_facts.py -q
```

**테스트 출력 로그:**
```text
..................                                                       [100%]
18 passed, 166 warnings in 2.88s
```

---

## 2. 검증 결론

- **어댑터 안정성:** OpenAI API 호출 타임아웃, 모델명 변수를 `settings`로부터 동적으로 바인딩하고 성공적으로 예외 복구(Fallback) 메커니즘이 활성화됨을 테스트 완료했습니다.
- **통합 파이프라인:** API 호출 실패 또는 키 미기입 상태에서도 500 오류가 발생하지 않고 기본 안내 메시지가 프론트엔드로 안전하게 전송됨을 확인했습니다.

---

## 3. 보완 검증 - 2026-06-24

Sprint 16 코드리뷰 이후 `/facts/auto-extract`가 실제 OpenAI adapter 경로를 사용하도록 보완하고 회귀 테스트를 추가했습니다.

### 3.1 추가 테스트 케이스

- `test_auto_extract_uses_openai_adapter_when_api_key_is_configured`
  - `OPENAI_API_KEY`가 설정된 상황에서 OpenAI adapter가 호출되고, AI 응답 fact가 `extraction_source="ai"`로 저장되는지 검증했습니다.
  - AI 후보는 자동 `confirmed` 처리하지 않고 `unknown` 상태로 저장되는지 확인했습니다.
- `test_auto_extract_falls_back_when_openai_adapter_fails`
  - OpenAI adapter가 예외를 발생시켜도 API가 500으로 실패하지 않고 `failed_sources`에 `ai_adapter_failed`를 남긴 뒤 deterministic fallback을 사용하는지 검증했습니다.

### 3.2 실행 명령 및 결과

```text
uv run --project backend pytest backend/tests/test_ai_adapter.py backend/tests/test_source_collector.py backend/tests/test_facts.py -q
결과:
29 passed, 182 warnings in 2.17s
```

```text
cd C:\page\frontend
npm.cmd run build
결과:
Compiled successfully
```

### 3.3 판정

- Sprint 16의 실제 AI adapter 연결, 실패 fallback, API 키 보안 가드 검증이 완료되었습니다.
- 경고는 기존 라이브러리 deprecation/FutureWarning 계열이며 기능 실패는 없습니다.
