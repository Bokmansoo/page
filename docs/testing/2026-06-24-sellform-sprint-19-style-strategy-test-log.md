# Sellform Sprint 19 Style Strategy Selection Test Log

**Test Date:** 2026-06-25  
**Tester:** Antigravity (AI pair programmer)  
**Status:** SUCCESS  

---

## 1. Backend Automated Tests

We created and executed a dedicated suite of unit and integration tests to validate candidate generation, fallback logic, and REST endpoints.

### 1.1 Style Strategy Service Unit Tests
**Command:**
```powershell
uv run --project backend pytest backend/tests/test_style_strategy_service.py -q
```
**Output:**
```text
......                                                                   [100%]
6 passed, 10 warnings in 0.07s
```
**Details:**
- `test_living_category_uses_problem_solution_frame`: Verified 7-step section order and names for the Living category.
- `test_fashion_category_uses_style_fit_frame`: Asserts `style_context` replaces `problem_statement` as the first section in Fashion.
- `test_beauty_category_uses_routine_frame`: Confirms Beauty replaces the first two sections with `skin_or_use_concern` and `ingredient_or_texture`.
- `test_food_category_uses_notice_frame`: Confirms Food replaces the first two sections with `intake_or_eating_context` and `ingredient_origin`.
- `test_generate_three_style_candidates_with_recommendation_and_channel_badges`: Checks that candidates return exactly 3 options and include recommended/suitability badges.
- `test_generate_candidates_feedback_adjusts_recommendation`: Assures feedback options (e.g., "더 스펙 중심으로", "더 감성적으로") dynamically change which candidate is AI recommended.

### 1.2 REST API Integration Tests
**Command:**
```powershell
uv run --project backend pytest backend/tests/test_style_strategy_api.py -q
```
**Output:**
```text
.                                                                        [100%]
1 passed, 18 warnings in 0.38s
```
**Details:**
- Verifies `GET /api/v1/projects/{project_id}/style-candidates` returns 3 valid candidates.
- Verifies `POST /api/v1/projects/{project_id}/style-candidates/{key}/select` saves choice to project's `selected_style` column.
- Verifies `POST /api/v1/projects/{project_id}/style-candidates/regenerate` updates recommended badge based on feedback options.
- Verifies `POST /api/v1/projects/{project_id}/page` page draft creation matches category structure (7 sections).

### 1.3 Full Test Suite Regression Test
**Command:**
```powershell
uv run --project backend pytest -q
```
**Output:**
```text
84 passed, 510 warnings in 11.82s
```
All existing tests passed, confirming zero regressions.

---

## 2. Frontend Build Validation

**Command:**
```cmd
cd frontend
npm.cmd run build
```
**Outcome:**
`Compiled successfully`
- Type validity and lint checks passed.
- Output bundle sizes validated.

---

## 3. Follow-up Validation - candidate key guard (2026-06-26)

Sprint 19 코드리뷰에서 확인된 보완점에 따라 잘못된 스타일 후보 키가 저장되지 않도록 백엔드 검증을 추가하고 회귀 테스트를 수행했습니다.

**Command:**

```powershell
uv run pytest tests/test_style_strategy_service.py tests/test_style_strategy_api.py -q
```

**Output:**

```text
9 passed, 21 warnings in 0.54s
```

**Added coverage:**

- `is_valid_style_candidate_key()`가 `problem_solution`, `spec_focused`, `lifestyle`만 허용하는지 검증.
- `POST /api/v1/projects/{project_id}/style-candidates/not-a-style/select` 호출 시 `400 Bad Request`를 반환하는지 검증.
- 잘못된 스타일 키가 `ProductProject.selected_style`에 저장되지 않는지 검증.
