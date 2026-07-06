# Sellform Sprint 16 Real AI Fact Extraction Code Review

**Sprint Goal:** `.env`에 설정된 API 키를 활용해 입력 텍스트와 이미지 OCR을 실제 AI(OpenAI)로 구조화 분석하고, 실패나 미설정 시 안전하게 fallback하는 기능을 구성합니다.

---

## 1. 주요 변경 파일 목록

- `backend/src/config.py` (AI 모델명, 타임아웃, Max Facts 설정 상수 추가)
- `backend/src/services/ai_adapter.py` (OpenAIAdapter 설정 매핑 연동 및 timeout 파라미터 적용)
- `.env.example` (AI Provider 및 Key 관련 템플릿 안내 행 추가)
- `docs/runbooks/2026-06-24-sellform-local-server-runbook.md` (로컬 환경 변수 설정 가이드 보완)

---

## 2. 코드 구조 검토 및 분석

### 2.1 AI 설정 바인딩 (`config.py`)

```python
    # AI Fact Extraction Configurations (Sprint 16)
    OPENAI_FACT_MODEL: str = "gpt-4o-mini"
    AI_FACT_EXTRACTION_TIMEOUT_SECONDS: int = 30
    AI_FACT_EXTRACTION_MAX_FACTS: int = 20
```
- Pydantic Settings를 기반으로 설정 변수를 안전하게 정의했습니다. 
- 환경 변수(`.env`)가 설정되지 않았을 때도 서비스 안정성을 유지할 수 있도록 적절한 기본값을 주입했습니다.

### 2.2 OpenAIAdapter 연동 보완 (`ai_adapter.py`)

- `OpenAIAdapter.__init__`에서 `model_name` 인자를 명시적으로 제공받지 못한 경우, `settings.OPENAI_FACT_MODEL`로 기본 매핑되도록 처리하여 환경설정 파일과의 바인딩을 달성했습니다.
- `extract_facts` 메쏘드 내의 `completions.parse` 호출부에 `timeout=settings.AI_FACT_EXTRACTION_TIMEOUT_SECONDS`를 명시적으로 적용함으로써, 외부 AI API의 지연 응답으로 인한 백엔드 블로킹 장애 전파를 방어했습니다.

### 2.3 로컬 런북 보완 (`local-server-runbook.md`)

- 비개발 직군 또는 로컬 인스톨 상황의 작업자가 쉽게 `.env` 파일을 복사/생성해 API 키를 적용할 수 있도록, 기입 예시와 주의사항(Git 커밋 금지)을 친절하게 문서화했습니다.

---

## 3. 종합 평가

- **유연성 (Flexibility):** 모델명이나 타임아웃 같은 상세 사양을 소스코드 하드코딩에서 분리하여 환경 변수로 동적 수정할 수 있도록 유연성을 증대했습니다.
- **안정성 (Stability):** 네트워크 지연에 대처하는 타임아웃을 명시해 API 요청의 생명주기를 안전하게 가둘 수 있게 되었습니다.
- **문서화 (Documentation):** API 키를 다루는 보안 규칙과 로컬 설정 방법을 세밀하게 런북에 문서화하여 향후 운영 난이도를 낮췄습니다.

---

## 4. 보완 리뷰 - 2026-06-24

초기 리뷰에서 확인된 핵심 누락 사항인 “facts 자동 생성 경로에서 실제 OpenAI adapter를 사용하지 않는 문제”를 보완했습니다.

### 4.1 조치 내용

- `backend/src/api/facts.py`
  - `OPENAI_API_KEY`가 설정되어 있으면 `/facts/auto-extract`가 `OpenAIAdapter`를 우선 호출하도록 연결했습니다.
  - AI 응답 fact를 `ExtractedFactCandidate`로 변환하고 `extraction_source="ai"`, `needs_review=True`, `verification_status="unknown"` 흐름으로 저장되도록 했습니다.
  - AI adapter 실패 시 API가 500으로 죽지 않고 `failed_sources`에 `source="ai"`, `reason="ai_adapter_failed"`를 기록한 뒤 기존 deterministic fallback을 사용하도록 했습니다.
- `backend/src/services/ai_adapter.py`
  - `get_ai_adapter("openai")` 기본 모델이 하드코딩 대신 `settings.OPENAI_FACT_MODEL`을 따르도록 수정했습니다.
- `.gitignore`
  - 실제 API 키가 들어가는 로컬 `.env` 파일이 Git에 올라가지 않도록 `.env`를 추가했습니다.

### 4.2 추가 테스트

- `test_auto_extract_uses_openai_adapter_when_api_key_is_configured`
  - API 키 설정 시 OpenAI adapter가 호출되고 AI fact 후보가 저장되는지 검증.
- `test_auto_extract_falls_back_when_openai_adapter_fails`
  - OpenAI adapter 실패 시 `failed_sources`에 실패 사유를 남기고 기존 fallback으로 계속 진행하는지 검증.

### 4.3 보완 검증 결과

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

### 4.4 최종 판정

- Sprint 16은 이제 실행계획의 핵심 완료 기준인 “API 키가 있으면 실제 AI adapter 경로 사용, 실패 시 안전 fallback, AI 후보 자동 confirmed 금지”를 충족합니다.
- 남은 경고는 기존 deprecation/FutureWarning 계열이며 이번 Sprint 16 보완으로 새로 발생한 실패는 없습니다.
