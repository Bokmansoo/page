# Sellform Sprint 44.5 AI Image Provider Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Sprint 44 visual jobs into real generated or edited image assets that preserve the uploaded product identity and can be consumed by Sprint 45 detail-page assembly.

**Architecture:** Keep the Sprint 44 image-job contract provider-neutral, then implement an `ImageGenerationProvider` boundary with OpenAI GPT Image as the first provider. Use image editing with original product photos for product-bearing scenes, reserve text-only generation for non-product supporting visuals, persist every job and output, and require seller approval before generated images become page assets.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, OpenAI Python SDK, GPT Image 1.5, existing `Asset` and job/audit models, Next.js, TypeScript.

**Official API Reference:** [OpenAI image generation guide](https://platform.openai.com/docs/guides/image-generation)

---

## File Structure

- Create: `backend/src/services/image_generation_provider.py` for provider-neutral request and result types.
- Create: `backend/src/services/openai_image_provider.py` for OpenAI Image API generation and editing.
- Create: `backend/src/services/image_generation_service.py` for authorization-independent job execution, storage, retries, and approval.
- Create: `backend/src/services/product_identity_validator.py` for product-preservation and output-quality checks.
- Modify: `backend/src/config.py` for image provider, model, output, and cost-tier settings.
- Modify: `backend/src/db/models.py` for persistent image generation jobs and output linkage.
- Modify: `backend/src/db/database.py` for SQLite development compatibility migrations.
- Create: `backend/src/api/image_generation.py` for generate, status, approve, reject, and regenerate endpoints.
- Modify: `backend/src/app.py` to register the image generation router.
- Create: `backend/tests/test_image_generation_provider.py`.
- Create: `backend/tests/test_image_generation_service.py`.
- Create: `backend/tests/test_image_generation_api.py`.
- Modify: `frontend/src/components/VisualPackagePanel.tsx` after Sprint 44 creates it.

## Non-Negotiable Generation Rules

- Product-bearing scenes must use one or more uploaded product images as references.
- Product color, silhouette, logo placement, controls, and distinguishing parts must not be intentionally redesigned.
- Text-only generation is allowed for backgrounds, textures, icons, and non-product supporting visuals.
- Marketing copy must remain editable page text; do not bake headlines, prices, claims, logos, or certification marks into generated images.
- Every generated output starts in `needs_review`; only an approved output may be selected by Sprint 45.
- A failed or rejected generation must not delete or replace an original uploaded asset.

## Tasks

### Task 1: Provider-Neutral Generation Boundary

**Files:**
- Create: `backend/src/services/image_generation_provider.py`
- Test: `backend/tests/test_image_generation_provider.py`

- [ ] Define `ImageGenerationRequest` with `job_id`, `role`, `prompt`, `negative_prompt`, `source_asset_paths`, `preserve_product_identity`, `size`, `quality`, and `transparent_background`.
- [ ] Define `ImageGenerationResult` with `content`, `mime_type`, `provider`, `model`, `revised_prompt`, and usage metadata.
- [ ] Define an `ImageGenerationProvider` protocol exposing `generate(request)`.
- [ ] Add validation tests requiring source assets whenever `preserve_product_identity=True`.
- [ ] Run:

```powershell
cd C:\page\backend
uv run pytest tests/test_image_generation_provider.py -q
```

- [ ] Expected result: all provider-contract tests pass without making a network request.

### Task 2: OpenAI GPT Image Adapter

**Files:**
- Create: `backend/src/services/openai_image_provider.py`
- Modify: `backend/src/config.py`
- Modify: `.env.example`
- Test: `backend/tests/test_image_generation_provider.py`

- [ ] Add settings:

```text
SELLFORM_IMAGE_PROVIDER=openai
SELLFORM_IMAGE_MODEL=gpt-image-1.5
SELLFORM_IMAGE_PREVIEW_MODEL=gpt-image-1-mini
SELLFORM_IMAGE_OUTPUT_FORMAT=png
```

- [ ] Use `client.images.edit(...)` when source images are supplied and `client.images.generate(...)` only for non-product visuals.
- [ ] Request transparent output for cutout roles and opaque output for lifestyle/background roles.
- [ ] Decode base64 output in memory and return it through `ImageGenerationResult`.
- [ ] Convert provider moderation, authentication, timeout, and rate-limit failures into stable internal error codes.
- [ ] Add mocked tests proving product-bearing jobs call the edit endpoint and background-only jobs call the generation endpoint.
- [ ] Run:

```powershell
cd C:\page\backend
uv run pytest tests/test_image_generation_provider.py -q
```

### Task 3: Persistent Job Execution And Asset Creation

**Files:**
- Create: `backend/src/services/image_generation_service.py`
- Modify: `backend/src/db/models.py`
- Modify: `backend/src/db/database.py`
- Test: `backend/tests/test_image_generation_service.py`

- [ ] Add persistent states: `planned`, `awaiting_cost_approval`, `generating`, `needs_review`, `approved`, `rejected`, and `failed`.
- [ ] Store visual role, source asset IDs, prompt, provider/model, cost tier, attempt count, output asset ID, error code, and timestamps.
- [ ] Reject source asset IDs that do not belong to the same project and workspace.
- [ ] Require explicit cost approval before invoking the provider.
- [ ] Save successful output under the existing upload/storage root and create an `Asset` with `source_type="ai_generated"`.
- [ ] Keep generated assets separate from originals and never mutate original files.
- [ ] Make execution idempotent: repeated requests for a `generating`, `needs_review`, or `approved` job must not create duplicate paid calls.
- [ ] Add service tests using a fake provider for success, retryable failure, permanent failure, and duplicate execution.
- [ ] Run:

```powershell
cd C:\page\backend
uv run pytest tests/test_image_generation_service.py -q
```

### Task 4: Product Identity And Quality Gate

**Files:**
- Create: `backend/src/services/product_identity_validator.py`
- Modify: `backend/src/services/image_generation_service.py`
- Test: `backend/tests/test_image_generation_service.py`

- [ ] Validate output MIME type, decodability, minimum dimensions, and non-empty pixel content.
- [ ] For product-preserving jobs, compare generated output against source assets for dominant product color and visible silhouette consistency.
- [ ] Mark uncertain outputs `needs_review` with concrete warnings; never silently approve them.
- [ ] Reject outputs containing requested marketing text, certification marks, or logos not present in source evidence.
- [ ] Add deterministic tests for invalid bytes, wrong dimensions, severe color drift, and a valid output.

### Task 5: Workspace-Scoped API

**Files:**
- Create: `backend/src/api/image_generation.py`
- Modify: `backend/src/app.py`
- Test: `backend/tests/test_image_generation_api.py`

- [ ] Add `POST /api/v1/projects/{project_id}/visual-jobs/{job_id}/generate` with `cost_approved: true`.
- [ ] Add `GET /api/v1/projects/{project_id}/visual-jobs/{job_id}`.
- [ ] Add `POST /api/v1/projects/{project_id}/visual-jobs/{job_id}/approve`.
- [ ] Add `POST /api/v1/projects/{project_id}/visual-jobs/{job_id}/reject`.
- [ ] Add `POST /api/v1/projects/{project_id}/visual-jobs/{job_id}/regenerate` with an optional revised prompt.
- [ ] Verify every endpoint scopes project, job, source assets, and output asset to the authenticated workspace.
- [ ] Add API tests for missing cost approval, cross-workspace access, invalid source assets, approval, rejection, and regeneration.
- [ ] Run:

```powershell
cd C:\page\backend
uv run pytest tests/test_image_generation_api.py -q
```

### Task 6: Visual Package Generation UI

**Files:**
- Modify: `frontend/src/components/VisualPackagePanel.tsx`

- [ ] Show original reference images, the generated result, role, prompt, cost tier, and identity warnings together.
- [ ] Keep `AI 이미지 만들기` disabled until the seller confirms the estimated cost tier.
- [ ] Show generation progress without blocking review of other visual roles.
- [ ] Provide `이 이미지 사용`, `다시 만들기`, `프롬프트 수정`, and `원본 사진 사용`.
- [ ] Ensure rejecting an AI image restores the original visual-plan selection.
- [ ] Run:

```powershell
cd C:\page\frontend
npm.cmd run build
```

### Task 7: Integration And Regression Verification

**Files:**
- Test: `backend/tests/test_image_generation_provider.py`
- Test: `backend/tests/test_image_generation_service.py`
- Test: `backend/tests/test_image_generation_api.py`
- Test: existing visual, page, export, and Figma suites.

- [ ] Run all image-generation tests with fake providers; CI must not make paid API calls.
- [ ] Run the full backend suite.
- [ ] Run the frontend production build.
- [ ] With explicit operator approval and a configured API key, manually generate one cutout and one lifestyle scene from an uploaded product photo.
- [ ] Confirm approved outputs appear as normal `Asset` records and rejected outputs are not selected by Sprint 45.

## Done Criteria

- A Sprint 44 `needs_generation` visual job can produce a real image asset.
- Product-bearing scenes use reference-image editing instead of unconstrained text-only generation.
- Generated images remain reviewable and reversible.
- Paid generation requires explicit seller approval.
- Sprint 45 can consume only original or seller-approved generated assets.
- Provider failures leave the existing-photo detail-page path usable.

