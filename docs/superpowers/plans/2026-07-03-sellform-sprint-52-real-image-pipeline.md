# Sellform Sprint 52 Real Image Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 이미지 기획 결과를 실제 이미지 생성/편집 작업으로 연결하고, 명시적 비용 승인과 상품 정체성 QA를 거쳐 상세페이지에 사용할 이미지를 선택하게 한다.

**Architecture:** 텍스트 LLM provider와 이미지 provider를 분리한다. 1차 이미지 provider는 OpenAI 이미지 생성/편집 모델로 두되, Sprint 52 테스트는 mock provider로만 검증한다. 실제 호출은 real mode와 비용 승인 조건을 모두 만족할 때만 허용한다.

**Tech Stack:** FastAPI, existing image generation services, Pydantic, pytest, Next.js.

---

## DESIGN.md Alignment

Sprint 52 connects real image generation, so image prompts, approvals, and review states must reinforce the visual direction in `DESIGN.md`.

Generated or edited images should support an editorial product preview and a selling detail page, not generic AI-art decoration.

Required behavior:

- Image plans should describe commercial detail page scenes, product usage, benefit emphasis, background direction, and section fit.
- Generated image cards must clearly label whether the image is uploaded, URL-extracted, mock-generated, or real-generated.
- Cost approval UI should use calm, plain commerce language rather than dramatic AI language.
- Product identity QA must be visible before generated images are treated as usable product evidence.
- Image generation states should use white-first surfaces and calm green/mint approval or success states.

Done Criteria addition:

- Real image pipeline output can be reviewed and inserted into the generated detail page while preserving the `DESIGN.md` soft commerce direction.

## Sprint 51 Mock Consistency Carryover

Before real image generation is connected, Sprint 52 must fix the mock result so it stays consistent with the seller's actual input.

Required behavior:

- If the user enters `삼탠바이미`, `스마트모니터`, or another product name, mock result copy and section titles must use that product context.
- Mock generation must not mix unrelated fixture products such as bicycle, massage, apparel, or food unless the input product is actually in that category.
- Uploaded images are the first-choice hero and section visual source in mock mode.
- If an uploaded image exists, the generated page must label it as `uploaded` and use it before any placeholder.
- If only a URL exists, URL-extracted images must be labeled as `url-extracted`.
- If neither uploaded image nor URL image exists, use a neutral commerce placeholder labeled `mock-generated`.
- Mock mode must never call external LLM or image APIs and must never spend API credits.

This carryover is intentionally part of Sprint 52 because real image generation cannot be trusted if the local mock flow already shows the wrong product.

## File Structure

- Modify: `backend/src/services/image_generation_provider.py`
- Modify: `backend/src/services/image_generation_service.py`
- Modify: `backend/src/services/product_identity_validator.py`
- Modify: `backend/src/api/image_generation.py`
- Modify: `backend/src/agents/mock_outputs.py`
- Modify: `backend/src/agents/graph.py`
- Create: `backend/tests/test_real_image_pipeline_contract.py`
- Create: `backend/tests/test_mock_generation_product_consistency.py`
- Modify: `frontend/src/components/VisualPackagePanel.tsx`
- Modify: `frontend/src/components/GenerationProgressShell.tsx`
- Create: `frontend/e2e/real-image-approval-flow.spec.ts`

## Tasks

### Task 0: Mock 입력 상품/업로드 이미지 일관성 보완

**Files:**
- Modify: `backend/src/agents/mock_outputs.py`
- Modify: `backend/src/agents/graph.py`
- Test: `backend/tests/test_mock_generation_product_consistency.py`

- [ ] **Step 1: Write failing consistency tests**

```python
import json


def test_mock_generation_uses_input_product_context(mock_agent_runner):
    result = mock_agent_runner(
        product_name="삼성 삼탠바이미 32인치 스마트모니터 TV + 무빙 스탠드",
        description="거실과 침실을 오가며 쓰는 이동형 스마트 모니터",
        uploaded_asset_id="asset-uploaded-samtan",
        uploaded_filename="삼탠바이미.png",
    )

    page_text = json.dumps(result["page_assembly"], ensure_ascii=False)

    assert "삼탠바이미" in page_text
    assert "스마트모니터" in page_text
    assert "자전거" not in page_text
    assert "마사지" not in page_text
    assert "의류" not in page_text


def test_mock_generation_prefers_uploaded_image_for_visual_slots(mock_agent_runner):
    result = mock_agent_runner(
        product_name="삼성 삼탠바이미 32인치 스마트모니터 TV + 무빙 스탠드",
        uploaded_asset_id="asset-uploaded-samtan",
        uploaded_filename="삼탠바이미.png",
    )

    hero_visual = result["page_assembly"]["sections"][0]["visual_slot"]

    assert hero_visual["source_type"] == "uploaded"
    assert hero_visual["asset_id"] == "asset-uploaded-samtan"
    assert "삼탠바이미.png" in hero_visual["label"]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd backend && uv run pytest tests/test_mock_generation_product_consistency.py -v`  
Expected: FAIL because current mock output may still use unrelated fixture copy or images.

- [ ] **Step 3: Implement deterministic product-aware mock output**

Implement mock generation rules:

- Build mock hero title, benefit sections, proof sections, and summary copy from `product_name`, `description`, URL metadata, and uploaded filename.
- Derive a simple product category only from the input. Do not fall back to unrelated fixture categories.
- Put uploaded assets into visual slots before generated placeholders.
- Keep placeholder visuals abstract and commerce-neutral when no real asset exists.
- Store visual source metadata as `uploaded`, `url-extracted`, or `mock-generated`.

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_mock_generation_product_consistency.py tests/test_real_image_pipeline_contract.py -v`  
Expected: PASS without real provider calls.

### Task 1: 이미지 provider 계약 강화

**Files:**
- Modify: `backend/src/services/image_generation_provider.py`
- Test: `backend/tests/test_real_image_pipeline_contract.py`

- [ ] **Step 1: Write failing test**

```python
from backend.src.services.image_generation_provider import ImageGenerationRequest, MockImageGenerationProvider


def test_image_provider_requires_cost_approval_for_real_jobs():
    provider = MockImageGenerationProvider()
    request = ImageGenerationRequest(
        job_id="job-1",
        prompt="밝은 거실에서 유아 자전거를 보여주는 상세페이지 이미지",
        reference_asset_ids=["asset-1"],
        requires_cost_approval=True,
        cost_approved=False,
    )
    result = provider.generate(request)
    assert result.status == "blocked_cost_approval"
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && uv run pytest tests/test_real_image_pipeline_contract.py -v`  
Expected: FAIL because request/result contract is missing or incomplete.

- [ ] **Step 3: Implement contract**

Ensure image generation requests include:

- `job_id`
- `prompt`
- `reference_asset_ids`
- `requires_cost_approval`
- `cost_approved`
- `product_identity_required`

- [ ] **Step 4: Run test**

Run: `cd backend && uv run pytest tests/test_real_image_pipeline_contract.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/image_generation_provider.py backend/tests/test_real_image_pipeline_contract.py
git commit -m "feat: enforce image generation approval contract"
```

### Task 2: 상품 정체성 QA 연결

**Files:**
- Modify: `backend/src/services/product_identity_validator.py`
- Modify: `backend/src/services/image_generation_service.py`
- Test: `backend/tests/test_real_image_pipeline_contract.py`

- [ ] **Step 1: Add identity QA test**

```python
def test_generated_product_image_requires_identity_check(image_generation_service):
    result = image_generation_service.review_generated_asset(
        source_asset_id="asset-original",
        generated_asset_id="asset-generated",
        product_identity_required=True,
    )
    assert result["identity_check"]["status"] in {"passed", "needs_review", "failed"}
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && uv run pytest tests/test_real_image_pipeline_contract.py::test_generated_product_image_requires_identity_check -v`  
Expected: FAIL.

- [ ] **Step 3: Implement deterministic identity check for tests**

In mock/test mode, return `needs_review` when confidence cannot be measured. Do not pretend identity is passed without evidence.

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_real_image_pipeline_contract.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/product_identity_validator.py backend/src/services/image_generation_service.py backend/tests/test_real_image_pipeline_contract.py
git commit -m "feat: add generated image identity review"
```

### Task 3: 이미지 승인 UI 연결

**Files:**
- Modify: `frontend/src/components/VisualPackagePanel.tsx`
- Create: `frontend/e2e/real-image-approval-flow.spec.ts`

- [ ] **Step 1: Update UI states**

Show:

- `비용 승인 필요`
- `생성 중`
- `검수 필요`
- `선택됨`
- `재생성`
- `이 이미지 사용`

- [ ] **Step 2: Add E2E test**

```ts
import { test, expect } from "@playwright/test";

test("image generation requires approval before use", async ({ page }) => {
  await page.goto("/workspace");
  await page.getByPlaceholder("상품명").fill("유아 자전거");
  await page.getByRole("button", { name: "AI 상세페이지 만들기" }).click();
  await expect(page.getByText("비용 승인 필요")).toBeVisible();
});
```

- [ ] **Step 3: Run E2E**

Run: `cd frontend && npm.cmd test -- --grep "image generation requires approval"`  
Expected: PASS with mock backend state.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/VisualPackagePanel.tsx frontend/e2e/real-image-approval-flow.spec.ts
git commit -m "feat: add image approval review UI"
```

## Done Criteria

- Real image jobs cannot run without explicit cost approval.
- Product-containing generated images require identity review.
- UI lets users approve, review, select, or regenerate images.
- Mock output remains consistent with the input product name, description, URL, and uploaded image before real image generation is enabled.
- Mock output does not show unrelated fixture products or irrelevant sample images.
- Uploaded image visual slots are labeled `uploaded`; URL images are labeled `url-extracted`; generated placeholders are labeled `mock-generated`.
- Tests use mock providers and do not spend credits.
