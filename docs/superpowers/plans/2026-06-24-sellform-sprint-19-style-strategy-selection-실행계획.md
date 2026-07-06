# Sellform Sprint 19 Style Strategy Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 상품별 상세페이지 생성 전에 7단 설득 구조와 카테고리별 변형 규칙을 적용하고, 디자인 미리보기와 판매 전략 설명이 포함된 스타일 후보 3개를 사용자가 선택할 수 있게 만든다.

**Architecture:** 기존 page-editor 생성 흐름 앞에 `style strategy selection` 단계를 추가한다. AI는 확인된 사실 카드와 카테고리를 기반으로 3개 스타일 후보를 만들고, 사용자는 후보를 선택한 뒤 상세페이지 초안을 생성한다.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, Next.js, TypeScript, React, Tailwind CSS, pytest, Vitest/Playwright where applicable.

---

## 1. 제품 결정

Sprint 19에서는 다음 UX 원칙을 구현 기준으로 삼는다.

- 상세페이지 기본 골격은 7단 설득 프레임을 사용한다.
- 카테고리별로 섹션 이름, 강조 순서, 문구 톤을 변형한다.
- 스타일 후보는 3개를 보여준다.
- 각 후보는 디자인 미리보기와 판매 전략 설명을 함께 보여준다.
- 하나의 후보에는 반드시 `AI 추천` 배지를 붙인다.
- 후보에는 `쿠팡 적합`, `스마트스토어 적합`, `둘 다 가능` 같은 채널 적합도 배지를 표시한다.
- 사용자는 반드시 하나의 스타일을 선택한 뒤 상세페이지 초안을 생성한다.
- 마음에 드는 후보가 없으면 `다른 스타일 다시 추천`을 누를 수 있다.

기본 7단 구조:

```text
1. 문제 제기
2. 메인 소구점 강조
3. 추가 장점
4. 메인 소구점 보강
5. 나머지 장점 정리
6. 한 문장 요약
7. 상품 정보
```

내부 section key:

```text
problem_statement
main_claim
secondary_benefit
main_claim_support
benefit_list
summary_claim
product_information
```

---

## 2. 파일 구조

### Backend

- Create: `backend/src/services/style_strategy_service.py`
  - 카테고리별 7단 구조 변형 규칙과 스타일 후보 생성 로직을 담당한다.
- Modify: `backend/src/api/page_editor.py` 또는 현재 상세페이지 생성 API 파일
  - 스타일 후보 조회/재추천/선택 API를 연결한다.
- Modify: `backend/src/models.py`
  - 필요 시 style candidate 또는 selected style 저장 모델을 추가한다.
- Test: `backend/tests/test_style_strategy_service.py`
  - 7단 구조, 후보 3개, AI 추천 배지, 채널 배지를 검증한다.

### Frontend

- Create or Modify: `frontend/src/.../StyleCandidateSelector.tsx`
  - 스타일 후보 3개 카드 UI를 담당한다.
- Modify: page-editor 진입 전 또는 page-editor 내부 생성 패널
  - 선택 전 상세페이지 생성 버튼을 비활성화한다.
- Test: 프론트 테스트가 이미 존재하면 후보 카드 렌더링 테스트를 추가한다.

### Docs

- Create: `docs/testing/2026-06-24-sellform-sprint-19-style-strategy-test-log.md`
- Create: `docs/reviews/2026-06-24-sellform-sprint-19-code-review.md`
- Create: `docs/troubleshooting/2026-06-24-sellform-sprint-19-style-strategy.md`

---

## 3. Task 1: 7단 설득 프레임과 카테고리별 변형 규칙 정의

**Files:**

- Create: `backend/src/services/style_strategy_service.py`
- Test: `backend/tests/test_style_strategy_service.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from backend.src.services.style_strategy_service import get_category_frame


def test_living_category_uses_problem_solution_frame():
    frame = get_category_frame("Living")

    assert [section.key for section in frame.sections] == [
        "problem_statement",
        "main_claim",
        "secondary_benefit",
        "main_claim_support",
        "benefit_list",
        "summary_claim",
        "product_information",
    ]
    assert frame.sections[0].label == "고객의 고민"
    assert frame.sections[-1].label == "상품 정보"
```

- [ ] **Step 2: 실패 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_style_strategy_service.py -q
```

Expected:

```text
FAILED ... ModuleNotFoundError 또는 ImportError
```

- [ ] **Step 3: 최소 구현**

`backend/src/services/style_strategy_service.py`에 다음 구조를 추가한다.

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class DetailPageSectionFrame:
    key: str
    label: str
    description: str


@dataclass(frozen=True)
class CategoryDetailPageFrame:
    category: str
    strategy: str
    sections: list[DetailPageSectionFrame]


BASE_SECTIONS = [
    DetailPageSectionFrame("problem_statement", "고객의 고민", "고객이 실제로 겪는 불편과 구매 전 고민을 짚습니다."),
    DetailPageSectionFrame("main_claim", "핵심 해결 메시지", "이 상품이 핵심 문제를 어떻게 해결하는지 말합니다."),
    DetailPageSectionFrame("secondary_benefit", "추가 장점", "메인 메시지 외에 체감 가능한 보조 장점을 말합니다."),
    DetailPageSectionFrame("main_claim_support", "왜 이 상품이어야 할까?", "핵심 메시지를 근거 중심으로 한 번 더 보강합니다."),
    DetailPageSectionFrame("benefit_list", "구매 전 확인할 장점들", "나머지 장점을 보기 쉽게 정리합니다."),
    DetailPageSectionFrame("summary_claim", "한 문장 요약", "전체 흐름을 구매 판단 문장으로 요약합니다."),
    DetailPageSectionFrame("product_information", "상품 정보", "구매 전 확인해야 할 스펙, 구성품, 주의사항을 정리합니다."),
]


def get_category_frame(category: str) -> CategoryDetailPageFrame:
    normalized = (category or "General").strip().lower()

    if normalized in {"living", "life", "home", "생활", "리빙"}:
        return CategoryDetailPageFrame("Living", "problem_solution", BASE_SECTIONS)

    if normalized in {"fashion", "패션", "잡화", "fashion_accessory"}:
        sections = [
            DetailPageSectionFrame("style_context", "어떤 스타일에 어울릴까?", "착용/사용 장면과 스타일 맥락을 먼저 제시합니다."),
            *BASE_SECTIONS[1:],
        ]
        return CategoryDetailPageFrame("Fashion", "style_fit", sections)

    if normalized in {"beauty", "cosmetic", "뷰티", "화장품"}:
        sections = [
            DetailPageSectionFrame("skin_or_use_concern", "사용 전 고민", "피부/사용감/루틴 관련 고민을 먼저 제시합니다."),
            DetailPageSectionFrame("ingredient_or_texture", "성분과 사용감", "확인된 성분, 제형, 사용감을 근거 중심으로 정리합니다."),
            *BASE_SECTIONS[2:],
        ]
        return CategoryDetailPageFrame("Beauty", "concern_ingredient_routine", sections)

    if normalized in {"food", "health", "식품", "건강식품"}:
        sections = [
            DetailPageSectionFrame("intake_or_eating_context", "언제 먹으면 좋을까?", "섭취/식사용 상황을 제시합니다."),
            DetailPageSectionFrame("ingredient_origin", "원재료와 기준", "원재료, 함량, 원산지, 보관 기준을 정리합니다."),
            *BASE_SECTIONS[2:],
        ]
        return CategoryDetailPageFrame("Food", "ingredient_context_notice", sections)

    return CategoryDetailPageFrame("General", "problem_solution", BASE_SECTIONS)
```

- [ ] **Step 4: 테스트 통과 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_style_strategy_service.py -q
```

Expected:

```text
1 passed
```

---

## 4. Task 2: 스타일 후보 3개 생성

**Files:**

- Modify: `backend/src/services/style_strategy_service.py`
- Test: `backend/tests/test_style_strategy_service.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
from backend.src.services.style_strategy_service import generate_style_candidates


def test_generate_three_style_candidates_with_recommendation_and_channel_badges():
    candidates = generate_style_candidates(
        category="Living",
        product_title="루메나 휴대용 무선 냉각선풍기",
        confirmed_facts=[
            "4,800mAh 배터리",
            "최대 18시간 무선 사용",
            "휴대용 무선 냉각 선풍기",
        ],
    )

    assert len(candidates) == 3
    assert sum(1 for candidate in candidates if candidate.is_ai_recommended) == 1
    assert all(candidate.name for candidate in candidates)
    assert all(candidate.sales_strategy for candidate in candidates)
    assert all(candidate.preview_summary for candidate in candidates)
    assert all(candidate.channel_fit in {"coupang", "smartstore", "both"} for candidate in candidates)
```

- [ ] **Step 2: 실패 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_style_strategy_service.py -q
```

Expected:

```text
FAILED ... generate_style_candidates not found
```

- [ ] **Step 3: 최소 구현**

`backend/src/services/style_strategy_service.py`에 다음을 추가한다.

```python
@dataclass(frozen=True)
class StyleCandidate:
    key: str
    name: str
    is_ai_recommended: bool
    channel_fit: str
    sales_strategy: str
    design_direction: str
    preview_summary: str
    reason: str


def generate_style_candidates(
    category: str,
    product_title: str,
    confirmed_facts: list[str],
) -> list[StyleCandidate]:
    facts_text = ", ".join(confirmed_facts[:3]) if confirmed_facts else "확인된 핵심 사실"
    title = product_title or "상품"

    return [
        StyleCandidate(
            key="problem_solution",
            name="문제 해결형",
            is_ai_recommended=True,
            channel_fit="both",
            sales_strategy="고객의 불편을 먼저 짚고 상품의 핵심 해결 메시지로 설득합니다.",
            design_direction="선명한 제목, 강한 소구점, 모바일에서 빠르게 읽히는 구조",
            preview_summary=f"{title}의 핵심 고민을 제기한 뒤 {facts_text}을 근거로 해결 메시지를 강조합니다.",
            reason="생활/리빙 상품은 실제 사용 불편과 해결 기대가 구매 판단에 큰 영향을 줍니다.",
        ),
        StyleCandidate(
            key="spec_focused",
            name="스펙 강조형",
            is_ai_recommended=False,
            channel_fit="coupang",
            sales_strategy="수치, 기능, 구성 정보를 빠르게 비교할 수 있게 보여줍니다.",
            design_direction="스펙 카드, 숫자 강조, 짧은 문장 중심",
            preview_summary=f"{facts_text}처럼 비교 가능한 정보를 전면에 배치합니다.",
            reason="쿠팡 사용자는 빠른 비교와 즉시 구매 판단을 선호하는 경우가 많습니다.",
        ),
        StyleCandidate(
            key="lifestyle",
            name="라이프스타일형",
            is_ai_recommended=False,
            channel_fit="smartstore",
            sales_strategy="사용 장면과 감성적 효용을 보여줘 구매 상상을 돕습니다.",
            design_direction="이미지 중심, 부드러운 문구, 사용 장면 강조",
            preview_summary=f"{title}을 일상 공간에서 어떻게 쓰는지 상상할 수 있게 구성합니다.",
            reason="스마트스토어에서는 브랜드감과 사용 맥락이 상세페이지 체류에 도움이 됩니다.",
        ),
    ]
```

- [ ] **Step 4: 테스트 통과 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_style_strategy_service.py -q
```

Expected:

```text
2 passed
```

---

## 5. Task 3: 스타일 선택 API 연결

**Files:**

- Modify: current page generation API file, likely `backend/src/api/page_editor.py`
- Test: current API test file or create `backend/tests/test_style_strategy_api.py`

- [ ] **Step 1: 실패 테스트 작성**

API 경로는 기존 라우터 패턴에 맞춰 다음 중 하나로 정한다.

```text
GET /api/projects/{project_id}/style-candidates
POST /api/projects/{project_id}/style-candidates/regenerate
POST /api/projects/{project_id}/style-candidates/{candidate_key}/select
```

테스트 예시:

```python
def test_style_candidates_api_returns_three_candidates(client, sample_project):
    response = client.get(f"/api/projects/{sample_project.id}/style-candidates")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["candidates"]) == 3
    assert any(candidate["is_ai_recommended"] for candidate in payload["candidates"])
```

- [ ] **Step 2: 실패 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_style_strategy_api.py -q
```

Expected:

```text
FAILED ... 404 Not Found
```

- [ ] **Step 3: API 구현**

기존 FastAPI router 패턴에 맞춰 `generate_style_candidates()`를 호출한다. 프로젝트의 `category`, `title`, `confirmed_facts`를 읽고 후보를 반환한다.

- [ ] **Step 4: 테스트 통과 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_style_strategy_api.py backend/tests/test_style_strategy_service.py -q
```

Expected:

```text
passed
```

---

## 6. Task 4: 프론트 스타일 후보 선택 UI

**Files:**

- Create or Modify: `frontend/src/.../StyleCandidateSelector.tsx`
- Modify: page-editor route or project workflow page

- [ ] **Step 1: UI 요구사항 반영**

카드 하나에는 다음 요소가 보여야 한다.

```text
스타일 이름
AI 추천 배지
채널 적합도 배지
디자인 미리보기 요약
판매 전략 설명
추천 이유
이 스타일로 상세페이지 만들기 버튼
```

- [ ] **Step 2: 선택 전 생성 제한**

스타일 후보를 선택하기 전에는 상세페이지 생성 버튼을 비활성화한다.

- [ ] **Step 3: 재추천 UX 추가**

`다른 스타일 다시 추천` 버튼을 추가하고, 재추천 이유 선택지를 제공한다.

```text
더 감성적으로
더 스펙 중심으로
더 쿠팡스럽게
더 스마트스토어스럽게
더 짧고 강하게
```

- [ ] **Step 4: 프론트 빌드 검증**

Run:

```powershell
cd frontend
npm.cmd run build
```

Expected:

```text
✓ built
```

---

## 7. 완료 기준

- 스타일 후보가 항상 3개 표시된다.
- 하나의 후보에는 `AI 추천` 배지가 있다.
- 모든 후보에는 판매 전략 설명과 디자인 미리보기 요약이 있다.
- 모든 후보에는 채널 적합도 배지가 있다.
- 사용자는 스타일을 선택한 뒤 상세페이지를 생성할 수 있다.
- 후보가 마음에 들지 않으면 재추천할 수 있다.
- 백엔드 테스트와 프론트 빌드가 통과한다.
- 테스트로그, 코드리뷰, 트러블슈팅 문서가 작성된다.

---

## 8. 검증 명령

```powershell
uv run --project backend pytest backend/tests/test_style_strategy_service.py backend/tests/test_style_strategy_api.py -q
cd frontend
npm.cmd run build
```
