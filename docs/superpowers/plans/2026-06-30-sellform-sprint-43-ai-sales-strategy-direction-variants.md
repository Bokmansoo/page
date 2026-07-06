# Sellform Sprint 43 AI Sales Strategy And Direction Variants Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate an AI sales strategy, a 30-second confirmation card, one recommended direction, and two alternatives.

**Architecture:** Reposition the current style candidate system as sales direction candidates. Add strategy fields before page generation so copy and visual layout are driven by "how to sell" rather than a simple style preset.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, existing `style_strategy_service`, React/TypeScript.

---

## File Structure

- Create: `backend/src/services/sales_strategy_service.py`.
- Modify: `backend/src/services/style_strategy_service.py` or wrap it to produce sales-direction-compatible output.
- Modify: `backend/src/api/pages.py` or create `backend/src/api/sales_strategy.py`.
- Create: `backend/tests/test_sales_strategy_service.py`.
- Create: `backend/tests/test_sales_strategy_api.py`.
- Create: `frontend/src/components/SalesStrategyConfirmationCard.tsx`.
- Create: `frontend/src/components/SalesDirectionSelector.tsx`.

## Tasks

### Task 1: Sales Strategy Model

- [ ] Define fields: `target_customer`, `buyer_problem`, `main_selling_point`, `supporting_points`, `tone`, `price_strategy`, `image_selection`, and `risk_notes`.
- [ ] Add deterministic test cases for a kids product, home product, and tech product.
- [ ] Map current `problem_solution`, `lifestyle`, and `spec_focused` styles to persuasion/emotional/information directions.

### Task 2: Fast Confirmation Card

- [ ] Build backend response that includes exactly the rows the user must confirm: target, main selling point, tone, price/discount, selected images.
- [ ] Each row must include `suggested_value`, `confidence`, and `edit_options`.
- [ ] Add API tests for missing price and missing image cases.

### Task 3: Direction Variants

- [ ] Generate one `recommended` direction and two `alternative` directions.
- [ ] Include representative headline, reason, section flow, target, and recommended visual mood.
- [ ] Ensure the selected direction writes through to `ProductProject.selected_style` or the successor sales-direction field.

### Task 4: Frontend Confirmation

- [ ] Show "AI가 이렇게 이해했어요. 맞나요?" after Sprint 42 understanding.
- [ ] Add `맞아요, 생성하기` and `조금 수정하기`.
- [ ] Show recommended direction as the large card, alternatives as smaller cards.
- [ ] Default to the AI-recommended direction if the user does nothing.

### Task 5: Backward Compatibility

- [ ] Existing `/style-candidates` callers should still work.
- [ ] Figma and PNG exports should still receive a style/direction key.
- [ ] Existing Sprint 37 tests should remain green.

### Task 6: Verification

- [ ] Run sales strategy tests.
- [ ] Run style strategy regression tests.
- [ ] Manually verify one product moves from understanding card to direction selection.

## Done Criteria

- The product no longer asks users to pick a vague style first.
- AI recommends a selling direction and explains why.
- Existing style candidate work becomes a foundation instead of a dead end.

