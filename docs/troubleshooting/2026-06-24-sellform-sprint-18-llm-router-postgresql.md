# Sellform Sprint 18 LLM Router & PostgreSQL Troubleshooting

본 문서는 Sprint 18 (LLM Router & PostgreSQL Setup) 구현 및 검증 과정에서 직면한 주요 이슈들의 진단 과정과 해결 방법을 상세히 기록한 문서입니다.

---

## 1. 직면한 오류 및 해결 조치

### Issue 1: `test_facts.py` 통합 테스트 실행 중 `TypeError` 및 AI 모킹 무시 현상

* **증상:** pytest 전체 구동 시 `test_auto_extract_uses_openai_adapter_when_api_key_is_configured` 등 일부 통합 테스트가 `TypeError: <lambda>() takes 0 positional arguments but 1 was given`으로 인해 깨짐.
* **원인 분석:**
  - 기존에는 `facts.py` 내에서 `OpenAIAdapter()`를 인자 없이 직접 인스턴스화했기 때문에 `monkeypatch.setattr(..., lambda: FakeOpenAIAdapter())`로 작성된 모킹 람다가 정상 동작했습니다.
  - Sprint 18에서 `LLMRouter`를 도입하면서 `settings.effective_openai_model`을 생성자에 매핑하여 넘겨주도록 변경되어, `OpenAIAdapter(model_name=effective_model)`과 같이 생성 시 인자(model_name)를 전달하게 되었습니다.
  - 이로 인해 생성자에서 인자를 수용하지 못하는 기존 람다가 호출되면서 `TypeError` 예외를 발생시켰고, 라우터는 이를 OpenAIAdapter 호출 실패로 오인하여 deterministic fallback(로컬 룰 기반 분석)으로 자동 떨어져서 검증하려던 팩트 개수 어설션(5개 vs 2개)이 불일치해 실패했습니다.
* **해결 조치:**
  - `test_facts.py`의 `monkeypatch` 구문을 가변인자를 넓게 수용하도록 갱신하여 인스턴스화 예외를 방지했습니다:
    ```python
    monkeypatch.setattr("src.services.llm_router.OpenAIAdapter", lambda *args, **kwargs: FakeOpenAIAdapter())
    ```
  - 모킹 경로 역시 `facts.py` 로컬 바인딩이 아닌 라우터가 실제로 로드하여 호출하는 `src.services.llm_router.OpenAIAdapter`로 교정하여 해결했습니다.

### Issue 2: PostgreSQL 환경 테스트 시 `UnicodeDecodeError` 발생

* **증상:** PostgreSQL 런타임 검증을 위해 `DATABASE_URL`을 로컬 PostgreSQL로 지정해 구동 시 `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xb8...` 에러와 함께 DB 연결이 거부됨.
* **원인 분석:**
  - 로컬 Windows OS 환경에 이미 다른 목적으로 수동 기동된 PostgreSQL 서비스가 디폴트 포트인 `5432`를 점유 중이었습니다.
  - 이 상태에서 도커에 띄운 `sellform-postgres`로 접속하려고 시도했으나, 기존 로컬 PostgreSQL로 요청이 전송되어 인증 실패(비밀번호 오류)를 초래했습니다.
  - libpq 클라이언트 라이브러리가 반환하는 윈도우 OS 인코딩(CP949)의 한글 인증 오류 메시지를 Python `psycopg2` 라이브러리가 UTF-8로 강제 디코딩하려고 시도하다가 디코더 크래시(`UnicodeDecodeError`)가 발생했습니다.
* **해결 조치:**
  - `docker-compose.yml` 내 db 서비스의 호스트 포트 바인딩 설정을 `5432:5432`에서 충돌 우려가 없는 **`5434:5432`**로 우회 설정했습니다.
  - `local-server-runbook.md` 및 테스트 실행 스크립트 상의 연결 포트 설정을 `5434`로 일괄 업데이트하여 로컬 PostgreSQL 테스트 무결성을 완수했습니다.

---

## 2. 운영 시 주의사항 (Operational Notes)

1. **포트 점유 상태 확인**:
   - 로컬 구동 전 `netstat -ano | findstr :5434` 명령을 활용하여 도커 PostgreSQL 포트가 온전히 점유 및 활용되고 있는지 재차 모니터링해야 합니다.
2. **글로벌 settings 싱글톤**:
   - `src.config.settings`는 글로벌 싱글톤 인스턴스이므로, 특정 파일에서 `monkeypatch.setattr`로 수정 시 백엔드 구동 환경 전체에 해당 설정값이 전파됨을 유의하고 독립 테스트 환경을 견지해야 합니다.
