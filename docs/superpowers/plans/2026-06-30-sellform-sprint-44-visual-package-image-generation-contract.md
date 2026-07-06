# Sellform Sprint 44 Visual Package And Image Generation Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Plan and represent the complete visual package for a detail page: product cuts, background scenes, lifestyle visuals, icons, badges, comparison graphics, and thumbnails.

**Architecture:** Start provider-agnostic. Define image jobs, visual roles, prompts, source assets, and generated asset records before binding to a paid image model. Reuse existing assets, visual background candidates, image mapping, and commerce visual cuts.

**Handoff:** This sprint produces validated `planned` or `needs_generation` jobs. Sprint 44.5 is the only stage that invokes a paid image provider and turns those jobs into reviewable `Asset` records.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, existing `Asset`, visual background service, image mapping, commerce visual cut builder.

---

## File Structure

- Create: `backend/src/services/visual_package_planner.py`.
- Create: `backend/src/services/image_generation_contract.py`.
- Modify: `backend/src/services/commerce_visual_cut_builder.py`.
- Modify: `backend/src/services/visual_background_service.py`.
- Create: `backend/tests/test_visual_package_planner.py`.
- Create: `backend/tests/test_image_generation_contract.py`.
- Create: `frontend/src/components/VisualPackagePanel.tsx`.

## Tasks

### Task 1: Visual Roles

- [ ] Define visual roles: `representative_product`, `cutout_product`, `lifestyle_scene`, `problem_scene`, `benefit_visual`, `detail_closeup`, `comparison_graphic`, `badge_set`, `faq_graphic`, `thumbnail`, `cta_visual`.
- [ ] Add tests that each standard detail page section receives a visual role.

### Task 2: Image Generation Contract

- [ ] Define image job fields: `role`, `source_asset_ids`, `prompt`, `negative_prompt`, `preserve_product_identity`, `output_size`, `cost_tier`, and `status`.
- [ ] Add deterministic contract tests.
- [ ] Do not call a paid image provider in this sprint.
- [ ] Ensure every `needs_generation` job contains enough source assets, prompt data, identity-preservation rules, output size, and cost tier for Sprint 44.5 to execute it without re-planning.

### Task 3: Visual Package Planner

- [ ] Given a sales strategy and project assets, produce required visuals.
- [ ] Prefer original product photos when they are suitable.
- [ ] Mark missing visuals with `needs_generation`.
- [ ] Provide prompt suggestions for each missing visual.

### Task 4: Existing Visual Services Repositioning

- [ ] Treat existing visual background candidates as visual mood suggestions.
- [ ] Treat image asset mapping as source-photo placement.
- [ ] Treat commerce visual cuts as page section visual slots.

### Task 5: Frontend Visual Package Review

- [ ] Add a panel that shows each visual role, current asset, generation need, and prompt.
- [ ] Provide actions: `이 사진 사용`, `AI 이미지 만들기`, `다른 연출 추천`, `직접 설명`.

### Task 6: Verification

- [ ] Run visual package tests.
- [ ] Confirm product photos appear before generated placeholders.
- [ ] Confirm every page section has a visual plan.

## Done Criteria

- Sellform can say exactly which images the final detail page needs.
- The system can distinguish existing photo usage from AI image generation.
- Future image-provider integration has a stable contract.
- Sprint 44.5 can consume every `needs_generation` job without guessing missing fields.
