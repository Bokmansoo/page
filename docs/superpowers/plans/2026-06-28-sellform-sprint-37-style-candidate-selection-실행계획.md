# Sprint 37 - 스타일 후보 선택 및 재생성 고도화 실행계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 상품과 카테고리에 맞는 상세페이지 스타일 후보 2~3개를 제안하고, 사용자가 선택하거나 다시 생성할 수 있게 하여 Figma/PNG 결과물의 디자인 방향을 명확히 제어한다.

**Architecture:** 상세페이지의 기본 7단 구조는 유지한다. 새 style strategy service가 상품 카테고리, 사실 카드, 이미지 상태를 기반으로 style candidates를 만들고, 선택된 style token이 Figma visual renderer와 PNG export에 반영된다.

**Tech Stack:** FastAPI, Python, PostgreSQL, TypeScript, Next.js, Figma Plugin API, Pytest, Playwright.

---

## 1. 배경

현재 Sellform은 상세페이지 구조와 카피를 만들 수 있지만, 사용자가 “어떤 디자인/판매 전략 방향으로 갈지”를 선택하는 경험이 약하다.

사용자가 원하는 UX는 다음과 같다.

- AI가 2~3개 스타일 후보를 보여준다.
- 각 후보는 디자인 느낌과 판매 전략을 함께 설명한다.
- 마음에 들지 않으면 “다른 스타일 다시 만들기”를 누른다.
- 선택한 스타일이 page-editor, PNG export, Figma Plugin 결과물에 일관되게 반영된다.

이번 Sprint 37은 “예쁜 색상 선택”이 아니라 “판매 전략 + 디자인 방향 선택”을 제품 흐름에 넣는 작업이다.

## 2. 범위

### 포함

- style candidate 데이터 모델 정의
- 카테고리별 기본 style strategy 정의
- style candidates 생성 API
- style 선택/저장 API
- page-editor에 스타일 후보 카드 UX 추가
- 선택된 style token을 Figma visual layout과 PNG export에 반영
- “다른 스타일 다시 추천” 기능

### 제외

- 이미지 생성 API 호출
- Figma MCP Remote OAuth 재도전
- 외부 마켓 업로드 자동화
- 실시간 A/B 테스트

## 3. 스타일 후보 기본값

### Living 카테고리 기본 후보

| style_key | 디자인 느낌 | 판매 전략 | 적합 상황 |
| --- | --- | --- | --- |
| `problem_solution` | 문제와 해결 전환이 선명한 구성 | 고객 불편과 해결 효과 강조 | 생활 문제 해결형 제품 |
| `spec_focused` | 숫자·아이콘·비교 정보 중심 | 성능과 근거 스펙 강조 | 기능·성능 경쟁 제품 |
| `lifestyle` | 따뜻한 배경, 사용 장면 중심 | 감성·생활 편의 강조 | 인테리어, 리빙 소품 |

### Fashion/Beauty/Food 확장 여지

이번 Sprint에서는 Living을 기준으로 완성하고, 다른 카테고리는 fallback style 후보만 제공한다.

## 4. 파일 구조

### Backend

- Modify: `backend/src/services/style_strategy_service.py`
  - style 후보 생성/재생성/선택 로직.
- Modify: `backend/src/services/figma_visual_layout_builder.py`
  - 선택된 style token을 visual layout에 반영.
- Modify: `backend/src/services/export_service.py` 또는 visual renderer service
  - 선택 style을 PNG export에 반영.
- Modify: `backend/src/api/pages.py`
  - style 후보 생성, 선택 API 추가.
- Test: `backend/tests/test_style_strategy_service.py`
- Test: `backend/tests/test_style_strategy_api.py`

### Frontend

- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
  - 스타일 후보 카드, 다시 추천, 선택 UX.
- Modify: `frontend/src/components/StyleCandidateSelector.tsx`
  - 후보 카드 전용 컴포넌트.
- E2E: `frontend/e2e/sprint37-style-candidate-selection.spec.ts`

### Figma Plugin

- Modify: `integrations/figma-plugin/src/visual-renderer.ts`
  - style token에 따라 color, typography, section style 변경.
- Test: `integrations/figma-plugin/tests/visual-renderer-style.test.ts`

### Docs

- Create: `docs/testing/2026-06-28-sellform-sprint-37-style-candidates-test-log.md`
- Create: `docs/reviews/2026-06-28-sellform-sprint-37-code-review.md`
- Create: `docs/troubleshooting/2026-06-28-sellform-sprint-37-style-candidates.md`

## 5. 데이터 계약

### style candidate 예시

```json
{
  "candidates": [
    {
      "style_key": "problem_solution",
      "label": "시원한 미니멀형",
      "design_summary": "블루톤, 넓은 여백, 청량한 제품 이미지 중심",
      "sales_strategy": "휴대성과 시원함을 먼저 보여주고 구매 불안을 낮춥니다.",
      "recommended": true,
      "preview_tokens": {
        "primary_color": "#0A62D6",
        "background_tone": "cool_gradient",
        "headline_style": "clean_bold"
      }
    }
  ]
}
```

### project 저장 필드

권장 방식:

- `ProductProject.selected_style`
- `ProductProject.style_candidates_snapshot`
- `ProductProject.style_generation`

만약 모델 변경 부담이 크면 Sprint 37에서는 project metadata JSON에 저장하고, 이후 정식 컬럼으로 승격한다.

## 6. 구현 작업

### Task 1: style candidate service 추가

**Files:**

- Modify: `backend/src/services/style_strategy_service.py`
- Test: `backend/tests/test_style_strategy_service.py`

- [ ] Step 1: 실패 테스트 작성

검증 내용:

```python
def test_living_category_generates_three_style_candidates():
    result = generate_style_candidates(category="Living", facts=facts, assets=assets)
    assert len(result.candidates) == 3
    assert result.candidates[0].style_key in {"problem_solution", "spec_focused", "lifestyle"}
    assert any(candidate.recommended for candidate in result.candidates)
```

- [ ] Step 2: 테스트 실패 확인

```cmd
uv run pytest backend/tests/test_style_strategy_service.py -q
```

- [ ] Step 3: rule-based 후보 생성 구현

초기 구현은 LLM 없이 deterministic rule 기반으로 만든다.

추천 우선순위:

- 고객 불편과 해결 효익이 선명함 → `problem_solution`
- 가격/스펙/인증/숫자 정보가 많음 → `spec_focused`
- 생활/인테리어/감성 키워드가 많음 → `lifestyle`

- [ ] Step 4: 테스트 통과 확인

```cmd
uv run pytest backend/tests/test_style_strategy_service.py -q
```

### Task 2: style 후보 API 추가

**Files:**

- Modify: `backend/src/api/pages.py`
- Test: `backend/tests/test_style_strategy_api.py`

- [ ] Step 1: API 실패 테스트 작성

API:

```http
GET /api/v1/projects/{project_id}/style-candidates
POST /api/v1/projects/{project_id}/style-candidates/regenerate
POST /api/v1/projects/{project_id}/style-candidates/{candidate_key}/select
```

select request:

```json
{
  "feedback": "스펙을 더 강조해줘"
}
```

- [ ] Step 2: 테스트 실패 확인

```cmd
uv run pytest backend/tests/test_style_strategy_api.py -q
```

- [ ] Step 3: API 구현

생성/재생성은 후보 snapshot을 저장한다. 선택 API는 selected style key를 저장한다.

- [ ] Step 4: API 테스트 통과

```cmd
uv run pytest backend/tests/test_style_strategy_api.py -q
```

### Task 3: page-editor 스타일 후보 UX

**Files:**

- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
- Modify: `frontend/src/components/StyleCandidateSelector.tsx`
- E2E: `frontend/e2e/sprint37-style-candidate-selection.spec.ts`

- [ ] Step 1: E2E 실패 테스트 작성

검증:

- page-editor에서 스타일 후보 영역이 보인다.
- 후보 카드 2~3개가 보인다.
- 후보 선택 시 selected 상태가 표시된다.
- “다른 스타일 다시 추천” 버튼이 보인다.

- [ ] Step 2: E2E 실패 확인

```cmd
cd C:\page\frontend
npx.cmd playwright test e2e/sprint37-style-candidate-selection.spec.ts
```

- [ ] Step 3: UI 구현

카드 구성:

- 디자인 미리보기 색상
- 스타일명
- 디자인 느낌
- 판매 전략
- 추천 뱃지
- 선택 버튼

- [ ] Step 4: 프론트 빌드

```cmd
cd C:\page\frontend
npm.cmd run build
```

### Task 4: Figma/PNG에 style token 반영

**Files:**

- Modify: `backend/src/services/figma_visual_layout_builder.py`
- Modify: `integrations/figma-plugin/src/visual-renderer.ts`
- Test: `integrations/figma-plugin/tests/visual-renderer-style.test.ts`

- [ ] Step 1: 선택 style이 visual payload에 포함되는지 테스트

예상 필드:

```json
{
  "style": {
    "style_key": "problem_solution",
    "primary_color": "#0A62D6",
    "background_tone": "cool_gradient"
  }
}
```

- [ ] Step 2: Figma renderer 테스트 작성

검증:

- `problem_solution`은 문제와 해결 영역의 대비를 분명하게 사용한다.
- `spec_focused`는 더 강한 숫자 계층과 정보 대비를 사용한다.
- `lifestyle`은 warm/soft background와 사용 장면을 사용한다.

- [ ] Step 3: renderer 구현
- [ ] Step 4: plugin test/build

```cmd
cd C:\page\integrations\figma-plugin
npm.cmd test
npm.cmd run build
```

### Task 5: 재생성 정책과 안전장치

**Files:**

- Modify: `backend/src/services/style_strategy_service.py`
- Test: `backend/tests/test_style_strategy_service.py`

- [ ] Step 1: 재생성 테스트 작성

검증:

- 같은 프로젝트에서 regenerate하면 이전 후보와 순서/톤이 달라질 수 있다.
- 이미 선택된 style은 사용자 확인 없이 덮어쓰지 않는다.
- 후보가 없으면 fallback 3종을 반환한다.

- [ ] Step 2: 테스트 통과 확인

```cmd
uv run pytest backend/tests/test_style_strategy_service.py -q
```

## 7. 검증 명령

```cmd
uv run pytest backend/tests/test_style_strategy_service.py backend/tests/test_style_strategy_api.py -q
cd C:\page\integrations\figma-plugin
npm.cmd test
npm.cmd run build
cd C:\page\frontend
npm.cmd run build
npx.cmd playwright test e2e/sprint37-style-candidate-selection.spec.ts
```

## 8. 완료 기준

- Living 상품에서 스타일 후보 3개가 생성된다.
- 사용자가 후보를 선택하고 다시 추천받을 수 있다.
- 선택한 스타일이 page-editor 미리보기, Figma Plugin 결과물, PNG export에 반영된다.
- 기본 7단 구조는 변하지 않는다.
- 자동 테스트, E2E, 수동 QA, 코드리뷰, 테스트로그, 트러블슈팅 문서가 남는다.

## 9. 2026-06-29 코드 정합성 보강

이 절은 현재 구현 경로를 기준으로 위 계획의 모호한 항목을 교정한다.

### 확정 파일

- Modify: `backend/src/services/style_strategy_service.py`
- Modify: `backend/src/api/pages.py`
- Modify: `backend/src/db/models.py`
- Modify: `backend/src/services/figma_visual_layout_builder.py`
- Modify: `backend/src/services/visual_page_renderer.py`
- Modify: `frontend/src/components/StyleCandidateSelector.tsx`
- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
- Modify: `integrations/figma-plugin/src/visual-renderer.ts`
- Test: `backend/tests/test_style_strategy_service.py`
- Test: `backend/tests/test_style_strategy_api.py`
- Create: `backend/tests/test_style_strategy_rendering.py`
- Create: `frontend/e2e/sprint37-style-candidate-selection.spec.ts`

신규 `style_candidate_service.py`를 만들지 않는다. 기존 `style_strategy_service.py`를 확장한다. API도 신규 router가 아니라 현재 `pages.py`의 다음 경로를 유지한다.

```text
GET  /api/v1/projects/{project_id}/style-candidates
POST /api/v1/projects/{project_id}/style-candidates/regenerate
POST /api/v1/projects/{project_id}/style-candidates/{candidate_key}/select
```

### 추가 TDD 작업

- [ ] **Step 1: 후보 스냅샷과 세대 번호 테스트 작성**

```python
def test_regeneration_persists_a_new_generation_without_overwriting_selection(
    client, project_with_confirmed_facts
):
    response = client.post(
        f"/api/v1/projects/{project_with_confirmed_facts.id}/style-candidates/regenerate",
        json={"feedback_option": "더 감성적으로"},
        headers=MOCK_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["generation"] == 2
    assert response.json()["selected_key"] == "problem_solution"
```

- [ ] **Step 2: 테스트 실패 확인**

```cmd
cd C:\page\backend
uv run pytest tests/test_style_strategy_api.py -q
```

Expected: 기존 응답에 `generation`이 없으므로 FAIL.

- [ ] **Step 3: 프로젝트 스타일 상태를 정식 컬럼으로 저장**

`ProductProject`에 `style_candidates_snapshot` JSON과 `style_generation` Integer를 추가한다. 선택된 `selected_style`은 재추천으로 덮어쓰지 않는다.

- [ ] **Step 4: 실제 시각 토큰 반영 테스트 작성**

```python
def test_selected_style_changes_figma_and_png_visual_tokens():
    figma = build_figma_visual_layout(project=project, page=page, assets=assets)
    png = build_visual_sections(project=project, page=page, assets=assets)
    assert figma["style"]["style_key"] == "lifestyle"
    assert png[0]["style"]["background_tone"] == figma["style"]["background_tone"]
```

- [ ] **Step 5: 렌더러 연결 구현 후 검증**

```cmd
cd C:\page\backend
uv run pytest tests/test_style_strategy_service.py tests/test_style_strategy_api.py tests/test_style_strategy_rendering.py -q
cd C:\page\integrations\figma-plugin
npm.cmd test
npm.cmd run build
```

- [ ] **Step 6: E2E에서 선택·재추천·유지 검증**

```cmd
cd C:\page\frontend
npx.cmd playwright test e2e/sprint37-style-candidate-selection.spec.ts
npm.cmd run build
```

새로고침 후 선택 유지, 재추천 후 기존 선택 유지, 다른 후보 선택 후 Figma/PNG 미리보기 토큰 변경을 검증한다.

### 보강 완료 기준

- 후보 세대와 후보 스냅샷이 프로젝트에 저장된다.
- 재추천이 기존 선택을 조용히 덮어쓰지 않는다.
- 선택한 판매 전략과 디자인 토큰이 Figma·PNG 양쪽에 동일하게 반영된다.
- Sprint 38의 마켓 패키지가 `selected_style`과 최종 상세페이지 버전을 참조할 수 있다.
