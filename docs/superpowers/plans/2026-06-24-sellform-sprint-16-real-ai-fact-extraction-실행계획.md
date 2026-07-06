# Sellform Sprint 16 Real AI Fact Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `.env`에 설정한 API 키를 사용해 입력 텍스트와 업로드 이미지 기반 사실 카드 후보를 실제 AI로 생성하고, 키가 없거나 실패할 때는 안전하게 fallback한다.

**Architecture:** Sprint 16은 URL 직접 수집이 아니라 “주어진 원문을 AI가 구조화하는 단계”를 완성한다. 백엔드는 provider adapter를 통해 OpenAI 우선 호출을 수행하고, 실패 시 deterministic fallback을 반환한다. 프론트엔드는 AI 사용 가능 여부, 비용/실패 안내, 후보 검수 흐름을 명확히 보여준다.

**Tech Stack:** FastAPI, Pydantic, OpenAI Python SDK, pytest monkeypatch, Next.js, TypeScript, `.env`, `.env.example`.

---

## 0. 배경

현재 Sellform에는 `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` 설정 자리가 있고, 사실 추출 adapter도 존재한다. 하지만 실사용 화면에서는 링크 직접 수집이 없고, API 키가 없을 때 fallback만 보이는 경우가 많다.

이 스프린트는 사용자가 직접 입력한 상품 설명 텍스트나 업로드 이미지 OCR 결과를 실제 AI로 분석해 사실 후보를 만드는 것을 목표로 한다.

## 1. 범위

### 포함

- `.env.example`에 AI 키 설정 섹션 추가.
- 로컬 서버 runbook에 API 키 설정 방법 추가.
- OpenAI API 키가 있을 때 실제 AI adapter 사용.
- API 키가 없을 때 mock/fallback 안내.
- AI 후보는 자동 `confirmed` 처리하지 않고 `unknown` 또는 `needs_revision`으로 저장.
- AI 응답 JSON schema 검증.
- timeout, rate limit, invalid key, malformed response 처리.
- 비용 추정을 위한 호출 provider/model/duration 로그 기록.

### 제외

- 쿠팡 링크 직접 수집.
- 외부 마켓 자동 업로드.
- 결제/구독/사용량 과금.
- 실시간 스트리밍 UI.

## 2. 대상 파일

| 파일 | 역할 |
| --- | --- |
| `.env.example` | API 키 설정 예시 |
| `docs/runbooks/2026-06-24-sellform-local-server-runbook.md` | 로컬 AI 키 설정 방법 |
| `backend/src/config.py` | AI 설정 변수 확인 및 필요 시 모델명 추가 |
| `backend/src/services/ai_adapter.py` | OpenAI 사실 추출 호출 및 schema 검증 |
| `backend/src/api/facts.py` 또는 현재 AI 사실 생성 endpoint | 실제 adapter 연결 |
| `backend/tests/test_ai_adapter.py` | adapter 단위 테스트 |
| `backend/tests/test_facts.py` | API 통합 테스트 |
| `frontend/src/app/workspace/projects/[projectId]/facts/page.tsx` | AI 사용 가능/실패 안내 |
| `docs/testing/2026-06-24-sellform-sprint-16-real-ai-test-log.md` | 테스트 증적 |
| `docs/reviews/2026-06-24-sellform-sprint-16-code-review.md` | 코드 리뷰 |
| `docs/troubleshooting/2026-06-24-sellform-sprint-16-real-ai.md` | 문제 해결 |

## 3. 환경 변수 기준

`.env.example`에는 실제 키를 넣지 않는다.

```env
# AI Provider Configuration
# 실제 키는 .env 파일에만 넣고 Git에 커밋하지 않습니다.
OPENAI_API_KEY=
OPENAI_FACT_MODEL=gpt-4o-mini
AI_FACT_EXTRACTION_TIMEOUT_SECONDS=30
AI_FACT_EXTRACTION_MAX_FACTS=20
```

로컬 `.env` 예시:

```env
DATABASE_URL=sqlite:///./sellform_run.db
UPLOAD_DIR=./uploads
MAX_UPLOAD_SIZE_MB=10
FACTORY_RAG_DEBUG_ENABLED=false
FACTORY_RAG_RUNTIME_MOCK=false

OPENAI_API_KEY=sk-...
OPENAI_FACT_MODEL=gpt-4o-mini
AI_FACT_EXTRACTION_TIMEOUT_SECONDS=30
AI_FACT_EXTRACTION_MAX_FACTS=20
```

## 4. Task 1: 설정과 문서를 정리한다

**Files:**

- Modify: `.env.example`
- Modify: `backend/src/config.py`
- Modify: `docs/runbooks/2026-06-24-sellform-local-server-runbook.md`

- [ ] **Step 1: `.env.example`에 AI 설정 섹션을 추가한다.**

반드시 실제 키 없이 빈 값만 둔다.

- [ ] **Step 2: `Settings`에 모델명과 timeout을 추가한다.**

필드 예시:

```python
OPENAI_FACT_MODEL: str = "gpt-4o-mini"
AI_FACT_EXTRACTION_TIMEOUT_SECONDS: int = 30
AI_FACT_EXTRACTION_MAX_FACTS: int = 20
```

- [ ] **Step 3: 로컬 서버 runbook에 키 설정 방법을 추가한다.**

포함 문구:

```text
C:\page\.env 파일을 만들고 OPENAI_API_KEY를 설정한 뒤 백엔드를 재시작해야 합니다.
키는 절대 Git에 커밋하지 않습니다.
```

## 5. Task 2: 실제 AI adapter 호출을 테스트 가능하게 만든다

**Files:**

- Modify: `backend/src/services/ai_adapter.py`
- Test: `backend/tests/test_ai_adapter.py`

- [ ] **Step 1: mock client로 성공 응답 테스트를 작성한다.**

검증 항목:

- `product_name`
- `recommended_category`
- `facts[0].fact_text`
- `facts[0].source_text`
- provider/model/duration metadata

- [ ] **Step 2: malformed JSON 또는 schema mismatch 테스트를 작성한다.**

Expected: adapter가 예외를 던지고 API 계층에서 fallback으로 전환할 수 있어야 한다.

- [ ] **Step 3: `OPENAI_FACT_MODEL` 설정을 adapter에 연결한다.**

OpenAI adapter 기본 모델이 하드코딩되어 있으면 settings 기반으로 바꾼다.

- [ ] **Step 4: 테스트를 실행한다.**

Run:

```powershell
uv run --project backend pytest backend/tests/test_ai_adapter.py -q
```

Expected: all pass.

## 6. Task 3: facts API에서 실제 AI 추출을 연결한다

**Files:**

- Modify: `backend/src/api/facts.py` 또는 현재 자동 사실 생성 endpoint
- Test: `backend/tests/test_facts.py`

- [ ] **Step 1: API 키 없음 테스트를 작성한다.**

Expected:

- HTTP 200
- `fallback_count`가 1 이상
- 사용자 안내 메시지에 API 키 미설정 또는 fallback 이유가 포함됨
- 후보가 자동 confirmed 되지 않음

- [ ] **Step 2: API 키 있음 테스트를 작성한다.**

monkeypatch로 adapter 응답을 고정한다.

Expected:

- AI 후보 2개 이상 생성
- 후보 상태는 `unknown` 또는 `needs_revision`
- `source_text`가 저장됨
- `confirmed`는 없음

- [ ] **Step 3: API 계층에 provider 선택 로직을 연결한다.**

규칙:

- `OPENAI_API_KEY`가 있으면 OpenAI adapter 사용.
- 키가 없으면 deterministic fallback.
- adapter 예외 발생 시 fallback과 실패 사유 반환.

- [ ] **Step 4: API 테스트를 실행한다.**

Run:

```powershell
uv run --project backend pytest backend/tests/test_facts.py -q
```

Expected: all pass.

## 7. Task 4: 프론트엔드 안내를 개선한다

**Files:**

- Modify: `frontend/src/app/workspace/projects/[projectId]/facts/page.tsx`

- [ ] **Step 1: AI 사용 가능 상태 메시지를 표시한다.**

예시:

```text
AI 키가 설정되어 있으면 입력 텍스트와 이미지에서 사실 후보를 생성합니다. 후보는 자동 확정되지 않습니다.
```

- [ ] **Step 2: fallback 메시지를 더 명확하게 표시한다.**

예시:

```text
AI 호출을 사용하지 못해 기본 분석으로 전환했습니다. .env의 OPENAI_API_KEY 설정을 확인해 주세요.
```

- [ ] **Step 3: 프론트 빌드를 실행한다.**

Run:

```powershell
cd C:\page\frontend
npm.cmd run build
```

Expected: build succeeds.

## 8. 완료 기준

- `.env`에 `OPENAI_API_KEY`가 있을 때 실제 AI adapter 경로가 사용된다.
- 키가 없거나 호출 실패 시 사용자에게 이유가 표시되고 작업이 중단되지 않는다.
- AI 후보는 자동 확정되지 않는다.
- 백엔드 테스트와 프론트 빌드가 통과한다.
- API 키 설정 문서가 runbook에 있다.
- 테스트 로그, 코드 리뷰, 트러블슈팅 문서가 남는다.
