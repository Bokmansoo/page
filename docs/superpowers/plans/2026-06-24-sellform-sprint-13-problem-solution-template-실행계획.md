# Sellform Sprint 13 Problem-Solution Narrative Template Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 확인된 상품 사실을 “문제 제기 → 핵심 소구점 → 보조 장점 → 요약 → 상품 정보” 흐름으로 배치하는 문제 해결형 상세페이지 템플릿을 추가한다.

**Architecture:** Sprint 13은 사실 추출 기능이 아니라 상세페이지 내러티브 구조를 고도화하는 작업이다. 기존 page generation API에 `narrative_template` 선택값을 추가하고, `problem_solution` 템플릿을 page generator가 명시적인 섹션 순서로 생성하도록 만든다. 기존 `modern/emotional/formal` style preset은 시각/문체 프리셋으로 유지하고, narrative template은 섹션의 설득 구조를 결정한다.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, Anthropic page generator fallback, pytest, Next.js page editor, TypeScript.

---

## 0. Sprint 13 배경

사용자가 제안한 상세페이지 구성 구조:

```text
1. 문제 제기: 고객의 핵심 고민에 대한 문제 제기
2. 메인 소구점 강조: 이 제품으로 핵심 문제를 제거할 수 있다
3. 소구점 B: 추가 장점
4. 소구점 A 보강: 메인 메시지 다시 강조
5. 소구점 B~D: 나머지 장점 정리
6. 소구점 요약: 전체 흐름을 한 문장으로 정리
7. 상품 정보: 최종 구매 판단용 정보
```

Sellform에서는 이 구조를 `problem_solution` narrative template으로 정의한다.

## 1. 범위

### 포함

- `problem_solution` 상세페이지 템플릿 정의.
- page generation 요청에 `narrative_template` 필드 추가.
- `problem_solution` 템플릿 섹션 타입 추가.
- 카테고리별 문제 제기/소구점 변형 규칙 추가.
- mock/fallback page generator에서도 동일한 섹션 구조 생성.
- page editor에서 narrative template 선택 UI 추가.
- 테스트/리뷰/트러블슈팅 문서 작성.

### 제외

- 새로운 사실 추출 기능.
- 이미지 OCR/멀티모달 분석.
- Figma export.
- 쿠팡/스마트스토어 자동 등록.
- 성과 데이터 기반 자동 템플릿 최적화.

## 2. 템플릿 구조

### 2.1 내부 코드값

```text
problem_solution
```

### 2.2 섹션 타입

| 순서 | section_type | 역할 |
| ---: | --- | --- |
| 1 | `problem_statement` | 고객의 핵심 고민 제기 |
| 2 | `main_claim` | 이 상품이 해결하는 핵심 메시지 |
| 3 | `secondary_benefit` | 보조 장점 1개 |
| 4 | `main_claim_support` | 메인 소구점 근거 보강 |
| 5 | `benefit_list` | 나머지 장점 B~D 정리 |
| 6 | `summary_claim` | 전체 구매 이유를 한 문장으로 요약 |
| 7 | `product_information` | 스펙, 구성품, 옵션, 주의사항 |

### 2.3 카테고리별 변형 규칙

| 카테고리 | 문제 제기 방향 | 주의점 |
| --- | --- | --- |
| Fashion | 코디 어려움, 착용감, 수납, 계절감 | 체형 보정·효과 과장 금지 |
| Beauty | 건조함, 칙칙함, 민감함, 사용감 | 치료·완치·의학적 효능 표현 금지 |
| Food | 간편 섭취, 맛, 원재료, 보관 | 질병 예방·치료 표현 금지 |
| Living | 불편함, 정리, 위생, 공간 부족 | 절대적 안전·무독성 표현 주의 |

## 3. 파일 구조

### 수정 대상

- `backend/src/services/page_generator.py`
  - narrative template enum/constant 추가.
  - `problem_solution` mock/fallback 생성 로직 추가.
  - AI system prompt에 narrative template 구조 지시 추가.
- `backend/src/api/pages.py`
  - `CreatePageRequest`에 `narrative_template` 필드 추가.
  - generator 호출 시 전달.
- `backend/tests/test_pages.py`
  - problem_solution 템플릿 섹션 순서 테스트 추가.
  - confirmed fact만 사용하는지 기존 테스트와 함께 검증.
- `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
  - 상세페이지 생성/재생성 UI에 narrative template 선택 추가.

### 신규 문서

- `docs/decisions/2026-06-24-sellform-narrative-template-strategy.md`
- `docs/testing/2026-06-24-sellform-sprint-13-template-test-log.md`
- `docs/reviews/2026-06-24-sellform-sprint-13-code-review.md`
- `docs/troubleshooting/2026-06-24-sellform-sprint-13-template.md`

## 4. Task 1: narrative template 전략 결정 문서 작성

**Files:**

- Create: `docs/decisions/2026-06-24-sellform-narrative-template-strategy.md`

- [ ] **Step 1: 결정 문서를 작성한다**

Create:

```markdown
# 결정 기록: Sellform 상세페이지 내러티브 템플릿 전략

- 날짜: 2026-06-24
- 상태: 제안

## 1. 배경

Sellform은 확정된 상품 사실을 바탕으로 상세페이지를 생성한다. 그러나 사실을 단순 나열하는 것만으로는 구매 설득력이 약하다. 상품별로 적합한 설득 구조를 선택할 수 있어야 한다.

## 2. 결정

상세페이지 생성에는 `style_preset`과 별도로 `narrative_template`을 둔다.

- `style_preset`: 시각 톤과 문체
- `narrative_template`: 섹션 순서와 설득 구조

첫 narrative template은 `problem_solution`으로 한다.

## 3. problem_solution 구조

1. 문제 제기
2. 메인 소구점
3. 보조 장점
4. 메인 소구점 보강
5. 장점 정리
6. 한 문장 요약
7. 상품 정보

## 4. 원칙

- 확인된 사실만 카피에 사용한다.
- 미확정 사실은 warnings에만 표시한다.
- 카테고리별 금지 표현을 지킨다.
- 모든 상품에 강제하지 않고 선택 가능한 템플릿으로 둔다.
```

## 5. Task 2: backend request schema와 generator signature 확장

**Files:**

- Modify: `backend/src/api/pages.py`
- Modify: `backend/src/services/page_generator.py`
- Test: `backend/tests/test_pages.py`

- [ ] **Step 1: failing test를 작성한다**

Add to `backend/tests/test_pages.py`:

```python
def test_create_page_with_problem_solution_template_generates_expected_section_order(client, db_session, test_setup):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    project_id = test_setup["project"].id

    response = client.post(
        f"/api/v1/projects/{project_id}/page",
        json={
            "style_preset": "modern",
            "narrative_template": "problem_solution",
        },
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    section_types = [section["section_type"] for section in body["sections"]]
    assert section_types == [
        "problem_statement",
        "main_claim",
        "secondary_benefit",
        "main_claim_support",
        "benefit_list",
        "summary_claim",
        "product_information",
    ]
```

- [ ] **Step 2: RED 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_pages.py::test_create_page_with_problem_solution_template_generates_expected_section_order -q
```

Expected:

```text
FAIL: section_types does not match expected problem_solution order
```

- [ ] **Step 3: `CreatePageRequest`를 확장한다**

Modify `backend/src/api/pages.py`:

```python
class CreatePageRequest(BaseModel):
    style_preset: Optional[str] = Field("modern", description="스타일 프리셋 (modern, emotional, formal)")
    primary_color: Optional[str] = Field(None, description="테마 주색상")
    narrative_template: Optional[str] = Field(
        "category_default",
        description="상세페이지 설득 구조 템플릿 (category_default, problem_solution)"
    )
```

- [ ] **Step 4: generator 호출에 narrative_template을 전달한다**

Modify `backend/src/api/pages.py`:

```python
generated_page = generator.generate_page(
    category=project.category or "Living",
    confirmed_facts=facts_data,
    style_preset=req.style_preset,
    primary_color=req.primary_color,
    narrative_template=req.narrative_template or "category_default",
)
```

- [ ] **Step 5: generator signature를 확장한다**

Modify `backend/src/services/page_generator.py`:

```python
def generate_page(
    self,
    category: str,
    confirmed_facts: List[Dict[str, Any]],
    style_preset: str = "modern",
    primary_color: Optional[str] = None,
    narrative_template: str = "category_default",
) -> GeneratedPageSchema:
```

그리고 mock fallback 호출도 동일하게 전달한다.

```python
return self._get_mock_page(category, confirmed_facts, primary_color, narrative_template)
```

## 6. Task 3: problem_solution mock/fallback 생성 로직 추가

**Files:**

- Modify: `backend/src/services/page_generator.py`
- Test: `backend/tests/test_pages.py`

- [ ] **Step 1: `_get_mock_page` signature를 확장한다**

```python
def _get_mock_page(
    self,
    category: str,
    confirmed_facts: List[Dict[str, Any]],
    primary_color: Optional[str] = None,
    narrative_template: str = "category_default",
) -> GeneratedPageSchema:
```

- [ ] **Step 2: problem_solution 분기를 추가한다**

`_get_mock_page` 초반에 추가:

```python
if narrative_template == "problem_solution":
    return self._get_problem_solution_mock_page(category, confirmed_facts, primary_color)
```

- [ ] **Step 3: helper를 추가한다**

Add to `PageGenerationService`:

```python
def _get_problem_solution_mock_page(
    self,
    category: str,
    confirmed_facts: List[Dict[str, Any]],
    primary_color: Optional[str] = None,
) -> GeneratedPageSchema:
    color = primary_color or "#3B82F6"
    fact_ids = [f["id"] for f in confirmed_facts]
    fact_summary = " ".join([f["fact_text"] for f in confirmed_facts]) if confirmed_facts else "확인된 상품 정보를 기준으로 구성했습니다."
    category_key = category.lower()

    problem_title_by_category = {
        "fashion": "매일 입을 옷, 예쁘기만 하면 충분할까요?",
        "beauty": "피부 고민, 아무 제품이나 고르기 어려우니까",
        "food": "매일 먹는 것일수록 원재료와 편의성이 중요합니다",
        "living": "작은 불편이 쌓이면 일상이 번거로워집니다",
    }
    problem_title = problem_title_by_category.get(category_key, "이 상품이 필요한 이유부터 짚어볼게요")

    return GeneratedPageSchema(
        theme_color=color,
        font_family="sans-serif",
        sections=[
            GeneratedSectionSchema(
                section_type="problem_statement",
                title=problem_title,
                body_copy="고객이 실제로 느끼는 불편과 구매 전 고민을 먼저 짚어줍니다.",
                associated_fact_ids=fact_ids[:1],
            ),
            GeneratedSectionSchema(
                section_type="main_claim",
                title="핵심 문제를 줄여주는 선택",
                body_copy=f"이 상품은 확인된 상품 정보를 바탕으로 핵심 구매 이유를 제안합니다. {fact_summary}",
                associated_fact_ids=fact_ids,
            ),
            GeneratedSectionSchema(
                section_type="secondary_benefit",
                title="함께 챙길 수 있는 추가 장점",
                body_copy="메인 소구점 외에도 사용자가 체감할 수 있는 보조 장점을 정리합니다.",
                associated_fact_ids=fact_ids[1:2],
            ),
            GeneratedSectionSchema(
                section_type="main_claim_support",
                title="왜 이 상품이어야 할까요?",
                body_copy="핵심 메시지를 다시 한 번 근거 중심으로 보강합니다.",
                associated_fact_ids=fact_ids[:2],
            ),
            GeneratedSectionSchema(
                section_type="benefit_list",
                title="구매 전 확인할 장점들",
                body_copy="나머지 장점을 보기 쉽게 정리해 구매 판단을 돕습니다.",
                associated_fact_ids=fact_ids,
            ),
            GeneratedSectionSchema(
                section_type="summary_claim",
                title="한 문장으로 정리하면",
                body_copy="필요한 이유와 기대할 수 있는 장점을 한 문장으로 요약합니다.",
                associated_fact_ids=fact_ids[:1],
            ),
            GeneratedSectionSchema(
                section_type="product_information",
                title="상품 정보",
                body_copy=f"최종 구매 판단에 필요한 정보입니다. {fact_summary}",
                associated_fact_ids=fact_ids,
            ),
        ],
    )
```

- [ ] **Step 4: GREEN 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_pages.py::test_create_page_with_problem_solution_template_generates_expected_section_order -q
```

Expected:

```text
1 passed
```

## 7. Task 4: AI prompt에 narrative template 구조 반영

**Files:**

- Modify: `backend/src/services/page_generator.py`

- [ ] **Step 1: problem_solution instruction을 추가한다**

Add helper:

```python
def _get_narrative_template_instruction(self, narrative_template: str) -> str:
    if narrative_template == "problem_solution":
        return (
            "상세페이지는 반드시 다음 7개 섹션 순서를 따르십시오: "
            "problem_statement(문제 제기), main_claim(메인 소구점), "
            "secondary_benefit(추가 장점), main_claim_support(메인 소구점 보강), "
            "benefit_list(나머지 장점 정리), summary_claim(한 문장 요약), "
            "product_information(상품 정보). "
            "각 섹션은 확인된 사실만 근거로 작성하고 associated_fact_ids를 정확히 연결하십시오."
        )
    return "카테고리와 스타일에 맞는 일반 상세페이지 구조를 생성하십시오."
```

- [ ] **Step 2: system prompt에 instruction을 포함한다**

```python
narrative_instruction = self._get_narrative_template_instruction(narrative_template)

system_prompt = (
    ...
    f"내러티브 템플릿 지시: {narrative_instruction}\n"
)
```

- [ ] **Step 3: tool schema description에 새 section_type을 반영한다**

`section_type` description에 다음 예시를 포함한다.

```text
problem_statement, main_claim, secondary_benefit, main_claim_support, benefit_list, summary_claim, product_information
```

## 8. Task 5: page editor UI에 narrative template 선택 추가

**Files:**

- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`

- [ ] **Step 1: 현재 page 생성 요청 위치를 찾는다**

Run:

```powershell
Select-String -LiteralPath "frontend\src\app\workspace\projects\[id]\page-editor\page.tsx" -Pattern "style_preset|/page|create|POST" -Context 3,5
```

- [ ] **Step 2: narrative template state를 추가한다**

Add near other page creation state:

```tsx
const [narrativeTemplate, setNarrativeTemplate] = useState("category_default");
```

- [ ] **Step 3: 선택 UI를 추가한다**

Add near style/theme controls:

```tsx
<label className="text-[10px] font-bold text-slate-400 uppercase">
  상세페이지 구조
</label>
<select
  value={narrativeTemplate}
  onChange={(event) => setNarrativeTemplate(event.target.value)}
  className="bg-slate-950/60 border border-slate-800 text-xs rounded-xl px-3 py-2 text-slate-300"
>
  <option value="category_default">카테고리 기본형</option>
  <option value="problem_solution">문제 해결형</option>
</select>
```

- [ ] **Step 4: page 생성 body에 narrative_template을 포함한다**

```tsx
body: JSON.stringify({
  style_preset: selectedStylePreset,
  primary_color: selectedPrimaryColor,
  narrative_template: narrativeTemplate,
})
```

- [ ] **Step 5: 프론트 빌드를 실행한다**

Run:

```powershell
cd C:\page\frontend
npm.cmd run build
```

Expected:

```text
Compiled successfully
```

## 9. Task 6: 테스트와 문서 산출물 작성

**Files:**

- Create: `docs/testing/2026-06-24-sellform-sprint-13-template-test-log.md`
- Create: `docs/reviews/2026-06-24-sellform-sprint-13-code-review.md`
- Create: `docs/troubleshooting/2026-06-24-sellform-sprint-13-template.md`

- [ ] **Step 1: 백엔드 테스트 실행**

Run:

```powershell
uv run --project backend pytest backend/tests/test_pages.py -q
uv run --project backend pytest -q
```

Expected:

```text
All tests passed
```

- [ ] **Step 2: 프론트 빌드 실행**

Run:

```powershell
cd C:\page\frontend
npm.cmd run build
```

Expected:

```text
Compiled successfully
```

- [ ] **Step 3: 테스트 로그 작성**

Create `docs/testing/2026-06-24-sellform-sprint-13-template-test-log.md`:

```markdown
# 테스트 실행 로그: Sellform Sprint 13 Problem-Solution Template

- 날짜: 2026-06-24
- 목적: 문제 해결형 상세페이지 템플릿이 올바른 섹션 순서와 confirmed fact 규칙을 따르는지 검증한다.

## 1. 백엔드 page 테스트

```text
uv run --project backend pytest backend/tests/test_pages.py -q
결과:
```

## 2. 전체 백엔드 회귀 테스트

```text
uv run --project backend pytest -q
결과:
```

## 3. 프론트 빌드

```text
npm.cmd run build
결과:
```

## 4. 수동 QA

- 문제 해결형 선택 가능 여부:
- 생성된 섹션 순서:
- confirmed fact만 사용 여부:

## 5. 판단
```

- [ ] **Step 4: 코드리뷰 문서 작성**

Create `docs/reviews/2026-06-24-sellform-sprint-13-code-review.md`:

```markdown
# 코드 리뷰: Sellform Sprint 13 (Problem-Solution Narrative Template)

| 항목 | 내용 |
| --- | --- |
| 브랜치 | `master` |
| 리뷰 일자 | 2026-06-24 |
| 리뷰 범위 | narrative_template API, problem_solution page generator, page editor template selector |
| 리뷰어 | Codex |
| 상태 | 검토 필요 |

## 1. 변경 요약

## 2. 계획 대비 충족 여부

| 기준 | 상태 | 근거 |
| --- | --- | --- |
| problem_solution 템플릿 섹션 순서 | 미확인 | `backend/tests/test_pages.py` |
| confirmed fact만 사용 | 미확인 | 기존 page tests |
| API narrative_template 계약 | 미확인 | `backend/src/api/pages.py` |
| page editor 선택 UI | 미확인 | page editor |
| 테스트/빌드 | 미확인 | testing log |

## 3. 이슈 목록

## 4. 테스트 증적

## 5. 결론
```

- [ ] **Step 5: 트러블슈팅 문서 작성**

Create `docs/troubleshooting/2026-06-24-sellform-sprint-13-template.md`:

```markdown
# 트러블슈팅: Sellform Sprint 13 Problem-Solution Template

## 1. 개요

## 2. 발견 이슈

### M1. 문제 해결형 템플릿이 일반 섹션으로 fallback됨

- 증상:
- 원인:
- 조치:

### M2. 섹션 순서가 깨짐

- 증상:
- 원인:
- 조치:

### M3. 미확정 사실이 카피에 들어갈 위험

- 증상:
- 원인:
- 조치:

## 3. 후속 과제

- 스펙 비교형 템플릿
- 감성 브랜딩형 템플릿
- 사용 장면형 템플릿

## 4. 결론
```

## 10. 완료 기준

- `problem_solution` narrative template으로 page 생성 요청을 보낼 수 있다.
- 생성된 page sections가 다음 순서를 따른다.

```text
problem_statement
main_claim
secondary_benefit
main_claim_support
benefit_list
summary_claim
product_information
```

- problem_solution 템플릿도 confirmed fact만 본문 카피에 사용한다.
- page editor에서 `카테고리 기본형`과 `문제 해결형`을 선택할 수 있다.
- 백엔드 page 테스트와 전체 회귀 테스트가 통과한다.
- 프론트 빌드가 통과한다.
- 테스트 로그, 코드리뷰, 트러블슈팅, 결정 문서가 남는다.

