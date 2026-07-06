# Sellform Sprint 23 LLM Web Browsing Fact Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 상품 링크만 입력해도 LLM이 웹 검색/브라우징 보조 도구를 통해 상품 정보를 수집하고, 근거가 있는 사실 카드 후보를 생성하도록 만든다.

**Architecture:** 기존 `httpx` URL 수집은 1차 시도로 유지하되, 실패하거나 본문이 부족하면 OpenAI Responses API의 web search 계층을 2차 수집기로 사용한다. LLM은 링크를 “마법처럼 직접 아는 것”이 아니라, 수집된 검색/페이지 요약 근거를 바탕으로 사실 후보를 만들고 모든 후보는 사용자 검수 전까지 미확정 상태로 둔다.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, OpenAI Responses API, LLM Router, pytest, Next.js, TypeScript.

---

## 1. 제품 결정

현재 사용자가 원하는 핵심 경험은 다음이다.

```text
상품 링크 입력 → AI가 링크 내용을 확인 → 사실 카드 자동 생성 → 사용자가 확인 → 상세페이지 생성
```

현재 구현은 다음처럼 동작한다.

```text
상품 링크 입력 → 백엔드 httpx 수집 → 수집 텍스트를 LLM에 전달 → 사실 카드 생성
```

문제는 쿠팡/스마트스토어 같은 쇼핑몰이 서버 직접 요청을 차단하는 경우가 많다는 점이다. 따라서 Sprint 23에서는 “일반 HTTP 수집 실패 후 LLM 웹 검색 기반 보조 수집”을 추가한다.

### 이번 스프린트에 하는 것

- OpenAI Responses API 기반 web search 수집 계층 추가
- URL 수집 실패 시 web search fallback 시도
- 수집된 근거 텍스트를 사실 카드 후보 생성에 연결
- provider/model/reason을 결과에 표시
- 사용자가 “AI가 무엇을 근거로 만들었는지” 볼 수 있게 한다

### 이번 스프린트에 하지 않는 것

- 로그인/캡차 우회
- 쿠팡/스마트스토어 관리자 자동 업로드
- 사용자의 브라우저 세션/쿠키 기반 수집
- Playwright/Chrome 실제 브라우저 자동 탐색

이 항목들은 Sprint 24에서 다룬다.

---

## 2. 파일 구조

### Backend

- Create: `backend/src/services/web_browsing_collector.py`
  - OpenAI Responses API 기반 URL/상품명 웹 정보 수집기.
- Modify: `backend/src/services/source_collector.py`
  - `httpx` 수집 실패 시 web browsing collector를 선택적으로 호출.
- Modify: `backend/src/services/llm_router.py`
  - Responses API/web search 실패 정보를 LLM 실패 결과에 포함.
- Modify: `backend/src/config.py`
  - web browsing 관련 설정 추가.
- Test: `backend/tests/test_web_browsing_collector.py`
  - API 키 없음, 검색 성공 mock, 검색 실패 fallback 검증.
- Test: `backend/tests/test_facts.py`
  - `/facts/auto-extract`가 URL 차단 시 web browsing collector 결과를 사실 후보에 반영하는지 검증.

### Frontend

- Modify: `frontend/src/app/workspace/projects/[id]/facts/page.tsx`
  - “링크 직접 수집 실패 → AI 웹 검색 보조 수집 시도 → 후보 생성” 상태 문구 표시.
  - 실패 시 복사 붙여넣기 fallback 안내 유지.

### Docs

- Create: `docs/testing/2026-06-26-sellform-sprint-23-llm-web-browsing-test-log.md`
- Create: `docs/reviews/2026-06-26-sellform-sprint-23-code-review.md`
- Create: `docs/troubleshooting/2026-06-26-sellform-sprint-23-llm-web-browsing.md`

---

## 3. 환경 변수

`.env.example`과 `.env`의 기준 설정은 다음을 따른다.

```env
SELLFORM_LLM_DEFAULT_PROVIDER=openai
SELLFORM_LLM_DEFAULT_MODEL=gpt-5.4-nano
SELLFORM_LLM_FALLBACK1_PROVIDER=google
SELLFORM_LLM_FALLBACK1_MODEL=gemini-2.5-flash
SELLFORM_LLM_FALLBACK2_PROVIDER=deterministic
SELLFORM_LLM_FALLBACK2_MODEL=local-rule-based
SELLFORM_LLM_ENABLE_FALLBACKS=true

SELLFORM_WEB_BROWSING_ENABLED=true
SELLFORM_WEB_BROWSING_PROVIDER=openai
SELLFORM_WEB_BROWSING_MODEL=gpt-5.4-nano
SELLFORM_WEB_BROWSING_TIMEOUT_SECONDS=30
SELLFORM_WEB_BROWSING_MAX_CHARS=12000
```

API 키가 없거나 OpenAI web search 호출이 실패하면 기존 deterministic fallback으로 내려간다.

---

## 4. Task 1: web browsing collector 인터페이스 추가

**Files:**
- Create: `backend/src/services/web_browsing_collector.py`
- Test: `backend/tests/test_web_browsing_collector.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from src.services.web_browsing_collector import WebBrowsingCollector


def test_web_browsing_collector_returns_disabled_when_api_key_missing(monkeypatch):
    monkeypatch.setattr("src.services.web_browsing_collector.settings.OPENAI_API_KEY", None)

    result = WebBrowsingCollector().collect(
        url="https://www.coupang.com/vp/products/example",
        product_name="루메나 휴대용 무선 냉각선풍기",
    )

    assert result.ok is False
    assert result.failure_reason == "web_browsing_api_key_missing"
    assert result.text == ""
```

- [ ] **Step 2: 테스트 실패 확인**

Run:

```cmd
cd /d C:\page
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_web_browsing_collector.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'src.services.web_browsing_collector'
```

- [ ] **Step 3: 최소 구현**

Create `backend/src/services/web_browsing_collector.py`:

```python
from dataclasses import dataclass

from src.config import settings


@dataclass(frozen=True)
class WebBrowsingCollectionResult:
    ok: bool
    text: str
    provider: str | None = None
    model: str | None = None
    failure_reason: str | None = None


class WebBrowsingCollector:
    def collect(self, url: str, product_name: str | None = None) -> WebBrowsingCollectionResult:
        if not settings.SELLFORM_WEB_BROWSING_ENABLED:
            return WebBrowsingCollectionResult(
                ok=False,
                text="",
                failure_reason="web_browsing_disabled",
            )

        if not settings.OPENAI_API_KEY:
            return WebBrowsingCollectionResult(
                ok=False,
                text="",
                provider=settings.SELLFORM_WEB_BROWSING_PROVIDER,
                model=settings.SELLFORM_WEB_BROWSING_MODEL,
                failure_reason="web_browsing_api_key_missing",
            )

        raise NotImplementedError("OpenAI Responses web search integration is implemented in Task 2.")
```

- [ ] **Step 4: 테스트 통과 확인**

Run:

```cmd
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_web_browsing_collector.py -q
```

Expected:

```text
1 passed
```

---

## 5. Task 2: OpenAI Responses API web search 호출 추가

**Files:**
- Modify: `backend/src/services/web_browsing_collector.py`
- Test: `backend/tests/test_web_browsing_collector.py`

- [ ] **Step 1: 성공 mock 테스트 추가**

```python
def test_web_browsing_collector_uses_openai_responses_web_search(monkeypatch):
    monkeypatch.setattr("src.services.web_browsing_collector.settings.OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("src.services.web_browsing_collector.settings.SELLFORM_WEB_BROWSING_MODEL", "gpt-5.4-nano")

    class FakeOutputText:
        type = "output_text"
        text = "4,800mAh 배터리와 최대 18시간 무선 사용 가능 정보가 확인되었습니다."

    class FakeMessage:
        content = [FakeOutputText()]

    class FakeResponse:
        output = [FakeMessage()]

    class FakeResponses:
        def create(self, **kwargs):
            assert kwargs["model"] == "gpt-5.4-nano"
            assert kwargs["tools"] == [{"type": "web_search_preview"}]
            assert "루메나 휴대용 무선 냉각선풍기" in kwargs["input"]
            return FakeResponse()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr("src.services.web_browsing_collector.OpenAI", lambda api_key: FakeClient())

    result = WebBrowsingCollector().collect(
        url="https://www.coupang.com/vp/products/example",
        product_name="루메나 휴대용 무선 냉각선풍기",
    )

    assert result.ok is True
    assert "4,800mAh" in result.text
    assert result.provider == "openai"
    assert result.model == "gpt-5.4-nano"
```

- [ ] **Step 2: 테스트 실패 확인**

Expected:

```text
ImportError or NotImplementedError
```

- [ ] **Step 3: 구현**

`backend/src/services/web_browsing_collector.py`에 OpenAI Responses 호출을 추가한다.

```python
from openai import OpenAI


def _extract_output_text(response) -> str:
    chunks: list[str] = []
    for output in getattr(response, "output", []) or []:
        for content in getattr(output, "content", []) or []:
            if getattr(content, "type", None) == "output_text":
                chunks.append(getattr(content, "text", ""))
    return "\n".join(chunk.strip() for chunk in chunks if chunk and chunk.strip())
```

`collect()`의 `raise NotImplementedError`를 다음으로 교체한다.

```python
client = OpenAI(api_key=settings.OPENAI_API_KEY)
query = (
    "다음 상품 링크와 상품명을 바탕으로 상세페이지 사실 카드에 쓸 수 있는 "
    "검증 가능한 상품 정보만 한국어로 요약하세요. "
    "근거가 불분명하면 추정하지 말고 불확실하다고 말하세요.\n\n"
    f"상품명: {product_name or ''}\n"
    f"상품 링크: {url}"
)

try:
    response = client.responses.create(
        model=settings.SELLFORM_WEB_BROWSING_MODEL,
        tools=[{"type": "web_search_preview"}],
        input=query,
        timeout=settings.SELLFORM_WEB_BROWSING_TIMEOUT_SECONDS,
    )
    text = _extract_output_text(response)
    if len(text) > settings.SELLFORM_WEB_BROWSING_MAX_CHARS:
        text = text[: settings.SELLFORM_WEB_BROWSING_MAX_CHARS]
    if not text.strip():
        return WebBrowsingCollectionResult(
            ok=False,
            text="",
            provider="openai",
            model=settings.SELLFORM_WEB_BROWSING_MODEL,
            failure_reason="web_browsing_empty_result",
        )
    return WebBrowsingCollectionResult(
        ok=True,
        text=text,
        provider="openai",
        model=settings.SELLFORM_WEB_BROWSING_MODEL,
    )
except Exception:
    return WebBrowsingCollectionResult(
        ok=False,
        text="",
        provider="openai",
        model=settings.SELLFORM_WEB_BROWSING_MODEL,
        failure_reason="web_browsing_failed",
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run:

```cmd
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_web_browsing_collector.py -q
```

Expected:

```text
2 passed
```

---

## 6. Task 3: source collector에 web browsing fallback 연결

**Files:**
- Modify: `backend/src/services/source_collector.py`
- Test: `backend/tests/test_facts.py`

- [ ] **Step 1: 통합 테스트 작성**

```python
def test_auto_extract_uses_web_browsing_when_url_fetch_is_blocked(client, db_session, setup_project, monkeypatch):
    project = setup_project(
        name="루메나 휴대용 무선 냉각선풍기",
        raw_input_url="https://www.coupang.com/vp/products/example",
        raw_input_text="",
    )

    monkeypatch.setattr(
        "src.services.source_collector.fetch_url_source",
        lambda url: URLCollectionResult(
            ok=False,
            url=url,
            host="www.coupang.com",
            text="",
            status_code=403,
            failure_reason="blocked_or_forbidden",
        ),
    )

    class FakeWebCollector:
        def collect(self, url, product_name=None):
            return WebBrowsingCollectionResult(
                ok=True,
                text="4,800mAh 배터리와 최대 18시간 무선 사용 가능 정보가 확인되었습니다.",
                provider="openai",
                model="gpt-5.4-nano",
            )

    monkeypatch.setattr("src.services.source_collector.WebBrowsingCollector", lambda: FakeWebCollector())

    response = client.post(f"/api/v1/projects/{project.id}/facts/auto-extract")

    assert response.status_code == 201
    body = response.json()
    assert body["created_count"] >= 1
    assert any("4,800mAh" in fact["source_text"] for fact in body["facts"])
```

- [ ] **Step 2: 테스트 실패 확인**

Expected:

```text
NameError: WebBrowsingCollector is not defined
```

- [ ] **Step 3: 구현**

`source_collector.py`에서 URL 수집 실패 시 web browsing fallback을 추가한다.

```python
from src.services.web_browsing_collector import WebBrowsingCollector
```

URL 실패 분기 이후 다음을 추가한다.

```python
            web_result = WebBrowsingCollector().collect(
                url=project.raw_input_url,
                product_name=project.name,
            )
            if web_result.ok and web_result.text.strip():
                sources.append(
                    CollectedSource(
                        source="url",
                        text=web_result.text.strip(),
                    )
                )
            else:
                failed_sources.append(
                    FailedSource(
                        source="url",
                        reason=web_result.failure_reason or "web_browsing_failed",
                        message=f"AI web browsing fallback failed: {web_result.failure_reason or 'web_browsing_failed'}",
                    )
                )
```

- [ ] **Step 4: 테스트 통과 확인**

Run:

```cmd
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_facts.py -q
```

Expected:

```text
passed
```

---

## 7. Task 4: 프론트 상태 문구 정리

**Files:**
- Modify: `frontend/src/app/workspace/projects/[id]/facts/page.tsx`

- [ ] **Step 1: 표시 문구 기준 적용**

다음 상태를 구분한다.

```text
링크 직접 수집 실패
AI 웹 검색 보조 수집 성공
AI 웹 검색 보조 수집 실패
근거 부족으로 수동 입력 필요
```

- [ ] **Step 2: 사용자가 이해할 수 있는 안내 추가**

`failed_sources` reason별 문구에 다음을 추가한다.

```ts
web_browsing_api_key_missing:
  "AI 웹 검색을 사용하려면 OpenAI API 키가 필요합니다. 상세 설명을 직접 붙여넣어 주세요.",
web_browsing_empty_result:
  "AI 웹 검색으로도 충분한 상품 정보를 찾지 못했습니다. 상세 설명을 복사해 붙여넣어 주세요.",
web_browsing_failed:
  "AI 웹 검색 보조 수집이 실패했습니다. 상품 상세 설명을 직접 붙여넣어 주세요.",
```

- [ ] **Step 3: 프론트 빌드 확인**

Run:

```cmd
cd /d C:\page\frontend
npm.cmd run build
```

Expected:

```text
Compiled successfully
```

---

## 8. 완료 기준

- 상품 URL 직접 수집이 차단되어도 OpenAI web search fallback을 시도한다.
- web search 성공 시 해당 텍스트를 근거로 사실 카드 후보가 생성된다.
- web search 실패 시 수동 입력 fallback 문구가 명확히 표시된다.
- AI가 만든 사실 후보는 자동 확정되지 않는다.
- 백엔드 테스트가 통과한다.
- 프론트 빌드가 통과한다.
- 테스트 로그, 코드리뷰 문서, 트러블슈팅 문서가 남는다.

