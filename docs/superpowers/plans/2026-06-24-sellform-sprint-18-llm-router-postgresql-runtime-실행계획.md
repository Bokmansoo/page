# Sellform Sprint 18 실행계획: LLM Router & PostgreSQL Runtime Setup

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to execute this plan.

## 1. 목표

Sprint 18의 목표는 Sellform의 AI 사실 추출 구조를 단일 OpenAI 호출에서 “LLM 라우터 기반 다중 Provider 구조”로 확장하고, 로컬 SQLite 중심 런타임을 유지하면서 PostgreSQL 운영 전환이 가능하도록 준비하는 것이다.

사용자가 원하는 기본 방향은 다음과 같다.

- 기본 LLM Provider: `openai`
- 기본 모델: `gpt-5.4-nano`
- 1차 fallback Provider: `google`
- 1차 fallback 모델: `gemini-2.5-flash`
- 최종 fallback: 기존 deterministic/local fallback
- 개발 기본 DB: SQLite 유지 가능
- 운영/구독형 서비스 준비 DB: PostgreSQL 지원

중요한 원칙은 “처음부터 LangGraph/LangChain으로 복잡하게 만들지 않고, 현재 FastAPI 서비스 구조 위에 가벼운 LLM Router를 얹는다”이다.

---

## 2. 현재 구조 판단

현재 Sellform은 LangGraph/LangChain 기반 에이전트 구조가 아니라 다음에 가까운 서비스 파이프라인 구조다.

```text
Frontend
  -> FastAPI API
    -> source_collector
    -> ai_adapter / deterministic fallback
    -> ProductFact DB 저장
    -> page-editor에서 상세페이지 생성/편집
```

따라서 Sprint 18에서는 “에이전트 프레임워크 도입”보다 아래 구조가 더 적합하다.

```text
Facts API
  -> LLM Router
      1. OpenAI: gpt-5.4-nano
      2. Google: gemini-2.5-flash
      3. deterministic fallback
  -> 후보 사실 카드 생성
  -> 사용자 검수 후 상세페이지 반영
```

LangGraph/LangChain은 이후 다음 조건이 생기면 검토한다.

- 리서치, 이미지 분석, 카피 생성, 규정 검수, 상세페이지 생성이 서로 독립 노드로 복잡하게 분기될 때
- 작업 상태를 그래프로 재시도/중단/재개해야 할 때
- 여러 도구를 오케스트레이션하는 실제 agent workflow가 필요할 때

---

## 3. 범위

### 포함

- `.env.example`과 로컬 `.env`에 LLM Router 설정 키를 추가한다.
- `backend/src/config.py`에 LLM Router 설정을 추가한다.
- `backend/src/services/llm_router.py`를 추가한다.
- 기존 `OpenAIAdapter`를 라우터에서 호출할 수 있게 정리한다.
- Google/Gemini Provider는 인터페이스와 설정을 먼저 열고, 실제 호출은 API 키가 있을 때만 활성화한다.
- 모든 AI 후보는 자동 확정하지 않고 `needs_review=True`, `verification_status="unknown"` 흐름을 유지한다.
- AI 실패 시 provider/model/failure reason을 반환하거나 로그에 남긴다.
- SQLite 기본 개발 흐름은 깨지지 않게 유지한다.
- PostgreSQL 연결 설정과 실행 방법을 runbook에 문서화한다.
- PostgreSQL 전환 시 필요한 smoke test 절차를 남긴다.

### 제외

- LangGraph/LangChain 도입
- 쿠팡/스마트스토어 업로드 자동화
- 유료 구독/결제 시스템
- 실제 외부 셀러 멀티테넌트 운영 배포
- CAPTCHA 우회, 로그인 우회, 비공개 페이지 크롤링

---

## 4. 환경 변수 설계

Sellform 공개 설정명은 `SELLFORM_LLM_*` 계열로 통일한다. 기존 `FACTORY_LLM_*` 계열은 하위 호환 alias로만 지원한다.

```env
# LLM Router Configuration
SELLFORM_LLM_DEFAULT_PROVIDER=openai
SELLFORM_LLM_DEFAULT_MODEL=gpt-5.4-nano
SELLFORM_LLM_FALLBACK1_PROVIDER=google
SELLFORM_LLM_FALLBACK1_MODEL=gemini-2.5-flash
SELLFORM_LLM_FALLBACK2_PROVIDER=deterministic
SELLFORM_LLM_FALLBACK2_MODEL=local-rule-based
SELLFORM_LLM_ENABLE_FALLBACKS=true

# Provider API Keys
OPENAI_API_KEY=
GEMINI_API_KEY=

# Fact Extraction Controls
AI_FACT_EXTRACTION_TIMEOUT_SECONDS=30
AI_FACT_EXTRACTION_MAX_FACTS=20
```

기존 `OPENAI_FACT_MODEL`은 하위 호환을 위해 바로 제거하지 않는다. Sprint 18에서는 `SELLFORM_LLM_DEFAULT_MODEL`을 우선 사용하고, 값이 없을 때만 기존 `OPENAI_FACT_MODEL`을 fallback으로 참조한다.

---

## 5. PostgreSQL 런타임 설계

로컬 초보 개발과 빠른 테스트는 SQLite가 편하다. 하지만 Sellform이 외부 셀러용 구독형 서비스로 확장되려면 PostgreSQL이 맞다.

### 권장 운영 방향

```text
개발 기본값:
  DATABASE_URL=sqlite:///./sellform_run.db

운영/구독형 준비:
  DATABASE_URL=postgresql://sellform:sellformpassword@localhost:5432/sellform_dev
```

### Sprint 18에서 해야 할 일

- SQLite와 PostgreSQL이 동일한 SQLAlchemy 모델로 동작하는지 확인한다.
- PostgreSQL 사용법을 runbook에 추가한다.
- `docker-compose.yml`에 PostgreSQL 서비스가 이미 있다면 실행 절차를 명확히 한다.
- PostgreSQL 연결 실패 시 앱이 이해 가능한 에러를 보여주도록 한다.

---

## 6. 구현 작업 순서

### Task 1. 설정 확장

파일:

- `.env.example`
- `.env`
- `backend/src/config.py`

작업:

- LLM Router 환경 변수를 추가한다.
- 기존 `OPENAI_FACT_MODEL`과 새 `SELLFORM_LLM_DEFAULT_MODEL`의 우선순위를 정한다.
- `GEMINI_API_KEY`를 Google fallback Provider용으로 명시한다.
- PostgreSQL 예시를 `.env.example`에 명확히 남긴다.

완료 기준:

- 환경 변수 없이도 기존 SQLite + deterministic fallback 테스트가 깨지지 않는다.
- `.env`에 실제 API 키 값은 비워둔다.

### Task 2. LLM Router 테스트 먼저 작성

신규 테스트:

- `backend/tests/test_llm_router.py`

검증 케이스:

- 기본 provider/model 순서가 `openai -> google -> deterministic`으로 구성된다.
- OpenAI 성공 시 Google fallback을 호출하지 않는다.
- OpenAI 실패 후 Google 성공 시 결과를 반환한다.
- OpenAI/Google 모두 실패하면 deterministic fallback으로 넘어간다.
- 실패 provider와 reason이 결과 metadata에 남는다.

명령:

```powershell
uv run --project backend pytest backend/tests/test_llm_router.py -q
```

### Task 3. LLM Router 구현

신규 파일:

- `backend/src/services/llm_router.py`

구현 방향:

- Provider 후보 목록을 설정에서 읽는다.
- 각 provider adapter를 순서대로 실행한다.
- provider별 timeout/failure를 잡아 전체 API를 죽이지 않는다.
- 최종적으로 다음 형태를 반환한다.

```python
{
    "provider": "openai",
    "model": "gpt-5.4-nano",
    "candidates": [...],
    "failed_sources": [...]
}
```

완료 기준:

- AI 호출 실패가 전체 facts API 실패로 이어지지 않는다.
- fallback 결과에도 어떤 provider가 실패했는지 알 수 있다.

### Task 4. Facts API 연동

파일:

- `backend/src/api/facts.py`

작업:

- 기존 direct `OpenAIAdapter` 호출을 `LLMRouter` 호출로 바꾼다.
- AI 결과는 계속 사용자 검수 상태로 저장한다.
- 후보 사실 카드에 provider/model metadata를 남긴다.
- fallback 안내 문구를 프론트에서 이해 가능한 형태로 유지한다.

테스트:

```powershell
uv run --project backend pytest backend/tests/test_ai_adapter.py backend/tests/test_facts.py backend/tests/test_llm_router.py -q
```

### Task 5. PostgreSQL 실행 문서와 smoke test

파일:

- `docs/runbooks/2026-06-24-sellform-local-server-runbook.md`
- `docs/troubleshooting/2026-06-24-sellform-sprint-18-llm-router-postgresql.md`

작업:

- SQLite 실행법과 PostgreSQL 실행법을 분리해서 적는다.
- PostgreSQL을 쓸 때의 `.env` 예시를 추가한다.
- 연결 실패, 포트 충돌, DB 미생성, 마이그레이션 누락 시 대응법을 적는다.

Smoke test:

```powershell
docker compose up -d db
uv run --project backend pytest backend/tests/test_facts.py -q
```

단, Docker가 없는 환경에서는 PostgreSQL smoke test를 “수동 미실행”으로 기록하고 SQLite 테스트를 필수로 통과시킨다.

### Task 6. 문서 산출물 작성

필수 산출물:

- `docs/decisions/2026-06-24-sellform-llm-router-and-db-runtime.md`
- `docs/testing/2026-06-24-sellform-sprint-18-llm-router-postgresql-test-log.md`
- `docs/reviews/2026-06-24-sellform-sprint-18-code-review.md`
- `docs/troubleshooting/2026-06-24-sellform-sprint-18-llm-router-postgresql.md`

---

## 7. 완료 기준

Sprint 18은 다음 조건을 모두 만족하면 완료로 본다.

- `.env.example`에 OpenAI 기본 Provider와 Google fallback Provider 설정이 있다.
- 실제 API 키가 없을 때도 기존 fallback 흐름이 깨지지 않는다.
- API 키가 있을 때 LLM Router가 설정된 순서대로 provider를 시도한다.
- AI 후보 사실 카드는 자동 확정되지 않는다.
- 실패 provider/model/reason이 테스트 또는 로그에서 확인된다.
- SQLite 개발 환경이 계속 동작한다.
- PostgreSQL 연결 방법이 문서화되어 있다.
- 백엔드 테스트가 통과한다.
- 프론트 빌드가 통과한다.
- 코드리뷰, 테스트로그, 트러블슈팅 문서가 남는다.

---

## 8. 검증 명령

```powershell
uv run --project backend pytest backend/tests/test_llm_router.py -q
uv run --project backend pytest backend/tests/test_ai_adapter.py backend/tests/test_facts.py backend/tests/test_llm_router.py -q
cd frontend
npm.cmd run build
```

PostgreSQL smoke test는 Docker 또는 로컬 PostgreSQL이 준비된 경우에만 실행한다.

```powershell
docker compose up -d db
$env:DATABASE_URL="postgresql://sellform:sellformpassword@localhost:5432/sellform_dev"
uv run --project backend pytest backend/tests/test_facts.py -q
```

---

## 9. 리스크와 대응

| 리스크 | 대응 |
| --- | --- |
| `gpt-5.4-nano` 모델 권한 또는 계정 접근 문제 | 실패 시 Google fallback 또는 deterministic fallback으로 내려간다. |
| Gemini API 키/SDK 미설치 | Sprint 18에서는 adapter 인터페이스와 fallback 구조를 우선 만들고, 키가 없으면 skip 처리한다. |
| PostgreSQL 설정이 로컬 초보 개발을 어렵게 만듦 | SQLite를 기본 개발 경로로 유지하고 PostgreSQL은 선택 경로로 둔다. |
| Provider 설정명이 늘어나 혼란스러움 | `.env.example`과 runbook에 “최소 설정”과 “운영 설정”을 분리해 적는다. |
| AI가 잘못된 사실을 생성함 | 자동 확정 금지, 사용자 검수 필수, 근거/출처 표시 유지. |

---

## 10. 다음 Sprint 후보

Sprint 18 이후에는 다음 중 하나로 이어가는 것이 좋다.

1. Sprint 19: PostgreSQL migration/seed/backup 운영 안정화
2. Sprint 20: LLM 사용량·비용·성공률 모니터링 대시보드
3. Sprint 21: LangGraph 도입 여부 검토 및 agent workflow 설계
4. Sprint 22: Figma MCP 디자인 협업 export/import 고도화
