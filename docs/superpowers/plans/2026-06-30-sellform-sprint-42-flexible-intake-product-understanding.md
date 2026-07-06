# Sellform Sprint 42 Flexible Intake And Product Understanding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a seller start with photos, URL, direct text, references, or any combination, then receive an AI-understood product summary card.

**Architecture:** Add a product intake layer in front of the current facts/project flow. Preserve existing `ProductProject`, `Asset`, and `ProductFact` models, but introduce a structured intake summary service that normalizes user inputs into product understanding candidates. The first user-visible flow should also establish the final light Sellform UI direction.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, Next.js, TypeScript, existing file upload/source collection/facts services.

---

## File Structure

- Create: `backend/src/services/product_intake_service.py` for normalizing input payloads.
- Create: `backend/src/services/product_understanding_service.py` for building the "AI가 이렇게 이해했어요" card.
- Modify: `backend/src/api/projects.py` to expose intake submit and understanding endpoints.
- Create: `backend/tests/test_product_intake_service.py`.
- Create: `backend/tests/test_product_understanding_api.py`.
- Modify: existing frontend theme or workspace styles to make the Sprint 42 entry flow light by default.
- Modify: `frontend/src/app/workspace/projects/new/page.tsx` or the current project creation entry to support photo/URL/text mixed input.
- Create: `frontend/src/components/ProductUnderstandingCard.tsx`.

## Tasks

### Task 1: Product Intake Contract

- [ ] Define `ProductIntakeInput` with fields for `urls`, `description`, `asset_ids`, `reference_urls`, and `competitor_urls`.
- [ ] Add tests that empty input is rejected and mixed input is accepted.
- [ ] Implement normalization that trims URLs/text and deduplicates URL lists.
- [ ] Verify with `cd C:\page\backend && uv run pytest tests/test_product_intake_service.py -q`.

### Task 2: Product Understanding Summary

- [ ] Build a deterministic first version of the understanding service from existing facts, filenames, URLs, and description text.
- [ ] Return `product_type`, `target_customer`, `buyer_problem`, `main_angle_candidates`, `tone_candidates`, `image_candidates`, and `unknowns`.
- [ ] Mark low-confidence fields as editable suggestions.
- [ ] Verify with service tests.

### Task 3: Backend API

- [ ] Add `POST /api/v1/projects/{project_id}/intake`.
- [ ] Add `GET /api/v1/projects/{project_id}/understanding`.
- [ ] Store the intake summary in project metadata or a dedicated JSON field if already available; otherwise use a service-derived response without schema migration in this sprint.
- [ ] Verify with API tests that uploaded assets and text inputs appear in the understanding response.

### Task 4: Frontend Entry Flow

- [ ] Apply the light UI direction to the first Sprint 42 surface: white page background, white input card, subtle borders, dark neutral text, muted helper text, Sellform green primary actions, and restrained AI accent color.
- [ ] Replace long upfront form behavior with a single mixed input surface: "상품 사진, URL, 설명 중 아무거나 넣어주세요."
- [ ] Show the product promise near the input: "사진/URL만 넣으면, 팔릴 이유부터 상세페이지까지."
- [ ] Support file upload, URL paste, and direct text.
- [ ] Show the understanding card after submission.
- [ ] Provide row-level actions: `이걸로 하기`, `다른 추천`, `직접 수정`.

### Task 5: Existing Implementation Reuse

- [ ] Use existing `Asset` upload data instead of inventing another file model.
- [ ] Use existing facts when present.
- [ ] Keep current facts confirmation screens available as an advanced/details path, not the first emotional moment.

### Task 6: Verification

- [ ] Run backend product intake tests.
- [ ] Run frontend build.
- [ ] Manually test: photo-only, URL-only, text-only, photo+URL.
- [ ] Manually inspect that the first screen and understanding card are light, clear, and solo-seller friendly rather than dark or developer-tool-like.
- [ ] Confirm the user sees product understanding before style/Figma/marketplace features.

## Done Criteria

- A seller can start with any available material.
- Sellform returns a concise product understanding card.
- The first intake and understanding experience uses the final light Sellform UI direction.
- Existing upload/fact infrastructure remains compatible.
- No Figma or marketplace UI is shown as the first success moment.
