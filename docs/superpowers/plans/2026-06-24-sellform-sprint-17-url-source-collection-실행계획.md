# Sellform Sprint 17 URL Source Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사용자가 상품 URL을 입력하면 Sellform이 정책과 실패 가능성을 고려해 원문 정보를 수집 시도하고, 성공한 텍스트를 AI 사실 후보 생성 입력으로 연결한다.

**Architecture:** Sprint 17은 URL을 상세페이지 생성 엔진 안에 깊게 넣지 않고, “source collector”라는 독립 계층으로 둔다. collector는 성공하면 source text snapshot을 저장하고, 실패하면 명확한 fallback 안내를 반환한다. 쿠팡/스마트스토어처럼 차단 가능성이 높은 사이트는 강제 크롤링하지 않고 사용자 복사 입력을 우선 fallback으로 제공한다.

**Tech Stack:** FastAPI, httpx or requests, BeautifulSoup/readability-style text extraction if already available, pytest, Next.js, existing AI fact extraction API.

---

## 0. 배경

사용자는 상품 링크만 넣으면 AI가 실제 상품 정보를 확인해 사실 카드를 만들어주길 기대한다. 현재 Sellform은 URL을 저장하지만 직접 수집은 하지 않고, 수동 텍스트와 업로드 이미지만 분석한다.

이 스프린트는 URL 자동 수집을 “시도 가능한 보조 기능”으로 추가한다. 외부 사이트 정책, 접근 차단, 동적 렌더링 실패 가능성이 있으므로 실패를 정상 경로로 설계한다.

## 1. 범위

### 포함

- 프로젝트의 source URL에서 원문 텍스트 수집 시도.
- 수집 성공 시 source snapshot 저장.
- 수집 실패 시 실패 사유와 수동 복사 안내 반환.
- 수집된 텍스트를 AI 사실 후보 생성 입력에 포함.
- URL host별 수집 결과 로그.
- 쿠팡/스마트스토어/일반 URL에 대한 실패/성공 테스트.
- 사용자에게 “링크 직접 수집은 시도했지만 실패할 수 있음”을 명확히 안내.

### 제외

- 로그인 필요한 페이지 수집.
- CAPTCHA 우회.
- 약관을 우회하는 강제 크롤링.
- 브라우저 자동화 기반 대량 수집.
- 마켓 상품 자동 등록.

## 2. 대상 파일

| 파일 | 역할 |
| --- | --- |
| `backend/src/services/source_collector.py` | URL 수집 서비스 |
| `backend/src/api/projects.py` 또는 facts API | source collection endpoint 연결 |
| `backend/src/models.py` | source snapshot 저장 모델이 필요할 경우 추가 |
| `backend/tests/test_source_collector.py` | collector 단위 테스트 |
| `backend/tests/test_facts.py` | 수집 텍스트가 AI 후보 생성에 들어가는지 테스트 |
| `frontend/src/app/workspace/projects/[projectId]/facts/page.tsx` | 수집 시도/실패/성공 UI |
| `docs/decisions/2026-06-24-sellform-url-collection-policy.md` | URL 수집 정책 결정 |
| `docs/testing/2026-06-24-sellform-sprint-17-url-collection-test-log.md` | 테스트 증적 |
| `docs/reviews/2026-06-24-sellform-sprint-17-code-review.md` | 코드 리뷰 |
| `docs/troubleshooting/2026-06-24-sellform-sprint-17-url-collection.md` | 문제 해결 |

## 3. URL 수집 정책

기본 원칙:

- 공개 접근 가능한 HTML만 수집한다.
- 로그인, CAPTCHA, 차단, 403, 429는 우회하지 않는다.
- 실패 시 사용자가 상품 설명을 복사해 붙여넣을 수 있게 안내한다.
- 수집된 텍스트는 “후보 생성 근거”로만 사용하고, 사실 카드는 사용자가 확인해야 한다.

정책 문서에 아래 표를 기록한다.

| Host 유형 | 처리 방식 | 실패 시 안내 |
| --- | --- | --- |
| 일반 공개 HTML | http fetch 후 text 추출 | 원문 설명 복사 붙여넣기 요청 |
| Coupang | fetch 시도, 403/동적 페이지면 fallback | 쿠팡 상세정보를 복사해 수동 텍스트로 붙여넣기 |
| SmartStore | fetch 시도, 동적/차단이면 fallback | 스마트스토어 상세정보를 복사해 붙여넣기 |
| 중국 도매처 | fetch 시도, 인코딩/차단 실패 허용 | 공급처 텍스트/이미지 업로드 안내 |

## 4. Task 1: source collector를 만든다

**Files:**

- Create: `backend/src/services/source_collector.py`
- Create: `backend/tests/test_source_collector.py`

- [ ] **Step 1: collector 결과 타입을 정의한다.**

필드:

```python
class SourceCollectionResult(BaseModel):
    ok: bool
    url: str
    host: str
    text: str
    status_code: int | None = None
    failure_reason: str | None = None
```

- [ ] **Step 2: 성공 테스트를 작성한다.**

mock HTTP 응답 HTML:

```html
<html><body><h1>루메나 휴대용 무선 냉각선풍기</h1><p>4,800mAh 대용량 배터리</p></body></html>
```

Expected:

- `ok == True`
- text에 상품명과 배터리 문구 포함

- [ ] **Step 3: 403 실패 테스트를 작성한다.**

Expected:

- `ok == False`
- `failure_reason`에 `blocked_or_forbidden` 포함

- [ ] **Step 4: collector를 구현한다.**

구현 규칙:

- timeout은 10초 이하.
- user-agent는 일반 브라우저 문자열을 사용하되 차단 우회 시도는 하지 않는다.
- script/style/nav/footer 텍스트는 제거한다.
- 텍스트는 20,000자 이하로 truncate한다.

- [ ] **Step 5: 테스트를 실행한다.**

Run:

```powershell
uv run --project backend pytest backend/tests/test_source_collector.py -q
```

Expected: all pass.

## 5. Task 2: facts 자동 생성에 source text를 연결한다

**Files:**

- Modify: `backend/src/api/facts.py` 또는 현재 자동 사실 생성 endpoint
- Test: `backend/tests/test_facts.py`

- [ ] **Step 1: URL 수집 성공 시 raw_text에 포함되는 테스트를 작성한다.**

Expected:

- source URL text가 AI adapter 입력에 포함된다.
- 생성 결과에 `extraction_source` 또는 failed/succeeded source 정보가 포함된다.

- [ ] **Step 2: URL 수집 실패 시 fallback 테스트를 작성한다.**

Expected:

- API가 500으로 죽지 않는다.
- `failed_sources`에 URL과 실패 이유가 들어간다.
- 기존 수동 텍스트/이미지가 있으면 계속 분석한다.

- [ ] **Step 3: API에 collector 호출을 연결한다.**

규칙:

- project source URL이 있으면 collector를 1회 호출한다.
- 수동 텍스트가 있으면 URL 수집 결과와 합쳐서 AI에 전달한다.
- 둘 다 없으면 현재처럼 “분석할 원문 없음” 안내를 반환한다.

- [ ] **Step 4: 테스트를 실행한다.**

Run:

```powershell
uv run --project backend pytest backend/tests/test_facts.py backend/tests/test_source_collector.py -q
```

Expected: all pass.

## 6. Task 3: 프론트엔드 안내를 개선한다

**Files:**

- Modify: `frontend/src/app/workspace/projects/[projectId]/facts/page.tsx`

- [ ] **Step 1: source collection 상태를 표시한다.**

상태 예시:

```text
상품 링크에서 원문 수집을 시도했습니다.
```

```text
상품 링크 수집에 실패했습니다. 상세 설명을 복사해 수동 텍스트로 붙여넣어 주세요.
```

- [ ] **Step 2: fallback CTA를 추가한다.**

버튼 또는 안내:

```text
상세 설명 붙여넣기
```

- [ ] **Step 3: 프론트 빌드를 실행한다.**

Run:

```powershell
cd C:\page\frontend
npm.cmd run build
```

Expected: build succeeds.

## 7. Task 4: 정책 문서를 작성한다

**Files:**

- Create: `docs/decisions/2026-06-24-sellform-url-collection-policy.md`

- [ ] **Step 1: 수집 원칙을 기록한다.**

반드시 아래 결정을 포함한다.

```text
Sellform은 외부 사이트 차단을 우회하지 않는다.
URL 수집 실패는 정상 경로로 취급한다.
수집된 원문은 사실 후보 생성에만 사용하고, 확인된 사실만 상세페이지 생성에 사용한다.
```

- [ ] **Step 2: host별 처리 방식을 표로 남긴다.**

Coupang, SmartStore, 일반 공개 HTML, 중국 도매처를 포함한다.

## 8. 완료 기준

- 일반 공개 HTML URL에서 텍스트를 수집할 수 있다.
- 차단/실패 URL에서도 API가 죽지 않고 fallback 안내를 반환한다.
- 수집 텍스트가 AI 사실 후보 생성 입력으로 연결된다.
- 프론트에서 수집 성공/실패 상태가 보인다.
- 외부 사이트 차단 우회가 구현되지 않는다.
- 백엔드 테스트와 프론트 빌드가 통과한다.
- 정책 결정, 테스트 로그, 코드 리뷰, 트러블슈팅 문서가 남는다.
