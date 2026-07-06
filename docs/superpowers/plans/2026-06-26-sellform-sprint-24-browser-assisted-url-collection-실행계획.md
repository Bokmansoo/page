# Sellform Sprint 24 Browser Assisted URL Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 일반 HTTP 수집과 LLM web search로도 부족한 상품 링크를 사용자가 브라우저에서 열어 확인하고, Sellform이 페이지 텍스트/스크린샷/선택 영역을 보조 수집해 사실 카드 후보로 연결하도록 만든다.

**Architecture:** Sprint 23은 서버형 web search fallback이고, Sprint 24는 사용자의 실제 접근 가능한 브라우저 화면을 중심으로 한 보조 수집 UX다. 쿠팡/스마트스토어의 정책을 우회하지 않고, 사용자가 직접 접근 가능한 페이지에서 복사/선택/스크린샷 기반으로 정보를 수집하는 안전한 흐름을 제공한다.

**Tech Stack:** Next.js, TypeScript, Browser Clipboard API, FastAPI, PostgreSQL, optional Playwright local helper, pytest, frontend build.

---

## 1. 제품 결정

브라우저 보조 수집의 핵심은 “자동 우회”가 아니라 “사용자가 보는 페이지에서 근거를 편하게 가져오는 것”이다.

### 이번 스프린트에 하는 것

- 링크 수집 실패 시 “브라우저로 열기” CTA 제공
- 사용자가 복사한 상세 설명을 한 번에 붙여넣으면 Sellform이 사실 카드 후보로 파싱
- 선택 텍스트/상세 설명/상품 스펙 블록을 bulk fact input으로 연결
- 이미지가 있을 경우 업로드 영역으로 안내
- 수집 방식과 근거 출처를 명확히 기록

### 이번 스프린트에 하지 않는 것

- 로그인 세션 탈취
- 캡차 우회
- 쿠팡/스마트스토어 관리자 자동 업로드
- 무인 크롤링 대량 수집

---

## 2. 파일 구조

### Frontend

- Modify: `frontend/src/app/workspace/projects/[id]/facts/page.tsx`
  - URL 수집 실패 시 브라우저 보조 수집 패널 표시.
  - “상품 페이지 열기”, “복사한 상세정보 붙여넣기”, “여러 사실로 변환” 액션 제공.
- Create: `frontend/src/components/BrowserAssistedSourcePanel.tsx`
  - 사용자가 외부 상품 페이지에서 복사한 텍스트를 붙여넣는 전용 패널.
- Modify: `frontend/src/app/workspace/projects/new/page.tsx`
  - 링크 입력 후 수집 실패가 예상되는 경우 수동 상세정보 입력 가이드 강화.

### Backend

- Modify: `backend/src/api/facts.py`
  - 기존 `/bulk` API를 브라우저 보조 붙여넣기 흐름에서 재사용.
- Create or Modify: `backend/src/services/bulk_fact_parser.py`
  - 복사한 긴 상세 설명을 개별 사실 후보로 분리하는 deterministic parser.
- Test: `backend/tests/test_bulk_fact_parser.py`
  - 줄 단위/불릿/콜론 기반 파싱 검증.

### Docs

- Create: `docs/guides/2026-06-26-sellform-browser-assisted-source-collection-guide.md`
- Create: `docs/testing/2026-06-26-sellform-sprint-24-browser-assisted-collection-test-log.md`
- Create: `docs/reviews/2026-06-26-sellform-sprint-24-code-review.md`
- Create: `docs/troubleshooting/2026-06-26-sellform-sprint-24-browser-assisted-collection.md`

---

## 3. Task 1: bulk fact parser 추가

**Files:**
- Create: `backend/src/services/bulk_fact_parser.py`
- Test: `backend/tests/test_bulk_fact_parser.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from src.services.bulk_fact_parser import parse_bulk_fact_text


def test_parse_bulk_fact_text_splits_lines_and_colon_specs():
    text = '''
    모델명: FAN JET ULTRA
    배터리: 4,800mAh
    최대 18시간 무선 사용 가능
    USB-C 충전 지원
    '''

    facts = parse_bulk_fact_text(text)

    assert "모델명: FAN JET ULTRA" in facts
    assert "배터리: 4,800mAh" in facts
    assert "최대 18시간 무선 사용 가능" in facts
    assert "USB-C 충전 지원" in facts
```

- [ ] **Step 2: 테스트 실패 확인**

Run:

```cmd
cd /d C:\page
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_bulk_fact_parser.py -q
```

Expected:

```text
ModuleNotFoundError
```

- [ ] **Step 3: 최소 구현**

Create `backend/src/services/bulk_fact_parser.py`:

```python
import re


def parse_bulk_fact_text(text: str, max_items: int = 50) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        line = re.sub(r"^[\\-\\*\\•\\d\\.\\)\\s]+", "", line).strip()
        if not line:
            continue
        if len(line) < 3:
            continue
        lines.append(line)

    unique: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = re.sub(r"\s+", "", line).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(line)
        if len(unique) >= max_items:
            break
    return unique
```

- [ ] **Step 4: 테스트 통과 확인**

Expected:

```text
1 passed
```

---

## 4. Task 2: 브라우저 보조 수집 패널 UI 추가

**Files:**
- Create: `frontend/src/components/BrowserAssistedSourcePanel.tsx`
- Modify: `frontend/src/app/workspace/projects/[id]/facts/page.tsx`

- [ ] **Step 1: UI 컴포넌트 추가**

`BrowserAssistedSourcePanel`은 다음 요소를 가진다.

```text
1. 상품 페이지 열기
2. 복사한 상세정보 붙여넣기 textarea
3. 여러 사실로 변환 버튼
4. 변환된 후보 미리보기
5. 사실 카드로 저장 버튼
```

- [ ] **Step 2: 링크 열기 동작**

상품 원본 링크가 있으면 새 탭으로 연다.

```tsx
<a href={sourceUrl} target="_blank" rel="noreferrer">
  상품 페이지 새 탭에서 열기
</a>
```

- [ ] **Step 3: 붙여넣은 텍스트를 `/facts/bulk`로 전송**

프론트는 줄 단위로 파싱하거나, Sprint 24 백엔드 parser API가 추가되면 서버 파싱 결과를 사용한다. 초기 구현은 프론트 줄 단위 파싱으로 충분하다.

```ts
const items = pastedText
  .split(/\r?\n/)
  .map((line) => line.trim())
  .filter((line) => line.length >= 3)
  .slice(0, 50)
  .map((line) => ({ fact_text: line, source_text: pastedText }));
```

- [ ] **Step 4: 프론트 빌드 확인**

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

## 5. Task 3: 사용자 가이드 문서 추가

**Files:**
- Create: `docs/guides/2026-06-26-sellform-browser-assisted-source-collection-guide.md`

- [ ] **Step 1: 가이드 작성**

가이드에는 다음 절차를 포함한다.

```text
1. 상품 링크 입력
2. AI 자동 수집 시도
3. 차단 시 상품 페이지 새 탭 열기
4. 상품명/스펙/상세 설명 복사
5. Sellform에 붙여넣기
6. 여러 사실로 변환
7. 후보 검수 후 확인됨 처리
8. 상세페이지 생성
```

- [ ] **Step 2: 주의사항 작성**

```text
Sellform은 로그인/캡차/접근 제한을 우회하지 않는다.
사용자가 볼 수 있는 상품 정보만 근거로 사용한다.
근거가 없는 내용은 상세페이지 카피에 사용하지 않는다.
```

---

## 6. 완료 기준

- URL 자동 수집 실패 시 사용자는 다음 행동을 명확히 알 수 있다.
- 상품 페이지를 새 탭으로 열 수 있다.
- 복사한 상세정보를 한 번에 붙여넣고 여러 사실 카드 후보로 만들 수 있다.
- 후보는 자동 확정되지 않고 사용자 검수를 거친다.
- 최소 3개의 확인된 사실 카드가 있으면 다음 단계로 진행할 수 있다.
- 프론트 빌드가 통과한다.
- 백엔드 테스트가 통과한다.
- 가이드/테스트로그/코드리뷰/트러블슈팅 문서가 남는다.

