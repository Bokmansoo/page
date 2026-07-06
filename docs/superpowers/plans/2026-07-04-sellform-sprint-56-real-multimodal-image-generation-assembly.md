# Sellform Sprint 56 Real Multimodal Image Generation Assembly Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 승인된 상품 이미지와 URL 추출 이미지를 기반으로 실제 상세페이지용 이미지 후보를 생성/편집하고, 텍스트 카피와 함께 판매 가능한 상세페이지 초안으로 조립한다.

**Architecture:** Text LLM과 Image provider를 분리한다. `visual_planning`은 이미지 작업 지시서를 만들고, `image_generation`은 비용 승인과 상품 정체성 검수를 통과한 작업만 실제 provider에 보낸다. `page_assembly`는 생성 이미지, 업로드 이미지, URL 추출 이미지를 섹션에 배치하고, `qa_review`는 이미지 누락과 상품 불일치를 차단한다.

**Tech Stack:** FastAPI, provider adapter, existing file/asset storage, OpenAI-compatible image provider interface, pytest, Next.js.

---

## File Structure

- Modify: `backend/src/config.py`
- Modify: `.env.example`
- Modify: `backend/src/services/image_generation_provider.py`
- Modify: `backend/src/services/image_generation_service.py`
- Modify: `backend/src/services/product_identity_validator.py`
- Modify: `backend/src/agents/nodes/visual_planning/agent.py`
- Modify: `backend/src/agents/nodes/image_generation/agent.py`
- Modify: `backend/src/agents/nodes/page_assembly/agent.py`
- Modify: `backend/src/agents/nodes/qa_review/agent.py`
- Create: `backend/tests/test_real_multimodal_image_generation_contract.py`
- Create: `backend/tests/test_page_assembly_with_generated_assets.py`
- Create: `backend/tests/test_qa_blocks_missing_or_unreviewed_images.py`
- Modify: `frontend/src/components/GenerationProgressShell.tsx`
- Modify: `frontend/src/components/GeneratedDetailPageResult.tsx`
- Modify: `frontend/src/components/ReviewEditorLayout.tsx`

## Tasks

### Task 1: 이미지 provider 설정과 비용 차단 계약

**Files:**
- Modify: `backend/src/config.py`
- Modify: `.env.example`
- Modify: `backend/src/services/image_generation_provider.py`
- Test: `backend/tests/test_real_multimodal_image_generation_contract.py`

- [ ] **Step 1: Write failing config/approval test**

```python
from backend.src.services.image_generation_provider import (
    ImageGenerationRequest,
    ImageGenerationProviderRouter,
)


def test_real_image_generation_is_blocked_without_cost_approval():
    router = ImageGenerationProviderRouter(mode="real", primary_provider="openai")
    request = ImageGenerationRequest(
        job_id="job-1",
        slot_id="hero",
        prompt="밝은 거실에서 스마트모니터가 공간을 넓게 쓰게 해주는 상세페이지 대표 이미지",
        reference_asset_ids=["asset-uploaded-1"],
        cost_approved=False,
        product_identity_required=True,
    )

    result = router.generate(request)
    assert result.status == "blocked_cost_approval"
    assert result.assets == []
```

- [ ] **Step 2: Run test and verify failure**

Run: `cd backend && uv run pytest tests/test_real_multimodal_image_generation_contract.py::test_real_image_generation_is_blocked_without_cost_approval -v`  
Expected: FAIL until router blocks unapproved real calls.

- [ ] **Step 3: Add config**

`.env.example` must include:

```dotenv
SELLFORM_IMAGE_PROVIDER=openai
SELLFORM_IMAGE_MODEL=gpt-image-1-mini
SELLFORM_IMAGE_GENERATION_MODE=mock
SELLFORM_IMAGE_COST_APPROVAL_REQUIRED=true
SELLFORM_IMAGE_MAX_CANDIDATES_PER_SLOT=3
```

`config.py` must expose these settings without reading or logging API keys.

- [ ] **Step 4: Implement provider router blocking**

`ImageGenerationProviderRouter.generate()` must:

- return `blocked_cost_approval` when real mode and `cost_approved=False`
- return mock placeholder assets in mock mode
- never call external provider in mock mode
- include provider/model fields in result metadata

- [ ] **Step 5: Run test and verify pass**

Run: `cd backend && uv run pytest tests/test_real_multimodal_image_generation_contract.py -v`  
Expected: PASS without spending credits.

### Task 2: Visual Planning이 상세페이지용 이미지 작업 지시서를 만든다

**Files:**
- Modify: `backend/src/agents/nodes/visual_planning/agent.py`
- Test: `backend/tests/test_real_multimodal_image_generation_contract.py`

- [ ] **Step 1: Write failing visual plan test**

```python
from backend.src.agents.nodes.visual_planning.agent import VisualPlanningAgent
from backend.src.agents.state import AgentRunState


def test_visual_planning_creates_commerce_image_jobs():
    state = AgentRunState(
        project_id="project-1",
        outputs={
            "page_planning": {
                "sections": [
                    {"section_id": "hero", "role": "hero"},
                    {"section_id": "comparison", "role": "problem"},
                ]
            },
            "copywriting": {
                "sections": {
                    "hero": {"title": "32인치에서 TV처럼, 모니터처럼"},
                    "comparison": {"title": "TV는 거실에만, 모니터는 책상에만 있었나요?"},
                }
            },
            "product_understanding": {
                "product_type": "smart_monitor",
                "identity_rules": ["화면과 무빙 스탠드 형태 보존"],
            },
        },
    )

    result = VisualPlanningAgent().run(state)
    jobs = result.outputs["visual_planning"]["image_jobs"]

    assert jobs[0]["slot_id"] == "hero"
    assert "상세페이지" in jobs[0]["prompt"]
    assert jobs[0]["product_identity_required"] is True
```

- [ ] **Step 2: Run test and verify failure**

Run: `cd backend && uv run pytest tests/test_real_multimodal_image_generation_contract.py::test_visual_planning_creates_commerce_image_jobs -v`  
Expected: FAIL until jobs are created.

- [ ] **Step 3: Implement image job planning**

Each visual job must include:

```python
{
    "job_id": "hero-1",
    "slot_id": "hero",
    "prompt": "상세페이지 대표 이미지...",
    "reference_asset_ids": ["asset-uploaded-1"],
    "candidate_count": 3,
    "product_identity_required": True,
    "estimated_cost_required": True,
}
```

- [ ] **Step 4: Run test and verify pass**

Run: `cd backend && uv run pytest tests/test_real_multimodal_image_generation_contract.py -v`  
Expected: PASS.

### Task 3: Image Generation Agent가 승인된 작업만 실제 생성 후보로 변환

**Files:**
- Modify: `backend/src/agents/nodes/image_generation/agent.py`
- Modify: `backend/src/services/image_generation_service.py`
- Test: `backend/tests/test_real_multimodal_image_generation_contract.py`

- [ ] **Step 1: Write failing image agent test**

```python
from backend.src.agents.nodes.image_generation.agent import ImageGenerationAgent
from backend.src.agents.state import AgentRunState


def test_image_generation_agent_records_blocked_jobs_when_not_approved():
    state = AgentRunState(
        project_id="project-1",
        outputs={
            "visual_planning": {
                "image_jobs": [
                    {
                        "job_id": "hero-1",
                        "slot_id": "hero",
                        "prompt": "상세페이지 대표 이미지",
                        "reference_asset_ids": ["asset-1"],
                        "product_identity_required": True,
                    }
                ]
            }
        },
        cost_approval_status="not_approved",
    )

    result = ImageGenerationAgent(mode="real").run(state)
    image_output = result.outputs["image_generation"]

    assert image_output["jobs"][0]["status"] == "blocked_cost_approval"
    assert image_output["candidates"]["hero"] == []
```

- [ ] **Step 2: Run test and verify failure**

Run: `cd backend && uv run pytest tests/test_real_multimodal_image_generation_contract.py::test_image_generation_agent_records_blocked_jobs_when_not_approved -v`  
Expected: FAIL until blocking is represented in agent output.

- [ ] **Step 3: Implement agent behavior**

`ImageGenerationAgent` must:

- read `visual_planning.image_jobs`
- call provider router only when `cost_approval_status == "approved"`
- write blocked job results otherwise
- store candidate assets under `outputs["image_generation"]["candidates"][slot_id]`
- preserve uploaded/URL candidates from Sprint 55 when no real asset exists

- [ ] **Step 4: Run test and verify pass**

Run: `cd backend && uv run pytest tests/test_real_multimodal_image_generation_contract.py -v`  
Expected: PASS.

### Task 4: Page Assembly가 실제 이미지와 카피를 상세페이지 섹션으로 조립

**Files:**
- Modify: `backend/src/agents/nodes/page_assembly/agent.py`
- Test: `backend/tests/test_page_assembly_with_generated_assets.py`

- [ ] **Step 1: Write failing assembly test**

```python
from backend.src.agents.nodes.page_assembly.agent import PageAssemblyAgent
from backend.src.agents.state import AgentRunState


def test_page_assembly_uses_real_generated_asset_when_selected():
    state = AgentRunState(
        project_id="project-1",
        selected_image_candidates={"hero": "candidate-real-hero"},
        outputs={
            "page_planning": {"sections": [{"section_id": "hero", "role": "hero"}]},
            "copywriting": {"sections": {"hero": {"title": "공간을 바꾸는 스마트 모니터", "body": "작은 공간에서도 화면을 자유롭게 배치하세요."}}},
            "image_generation": {
                "candidates": {
                    "hero": [
                        {
                            "candidate_id": "candidate-real-hero",
                            "asset_id": "asset-real-hero",
                            "source_type": "real-generated",
                            "identity_check": {"status": "needs_review"},
                        }
                    ]
                }
            },
        },
    )

    result = PageAssemblyAgent().run(state)
    section = result.outputs["page_assembly"]["sections"][0]

    assert section["title"] == "공간을 바꾸는 스마트 모니터"
    assert section["visual_slot"]["asset_id"] == "asset-real-hero"
    assert section["visual_slot"]["source_type"] == "real-generated"
```

- [ ] **Step 2: Run test and verify failure**

Run: `cd backend && uv run pytest tests/test_page_assembly_with_generated_assets.py -v`  
Expected: FAIL until assembly uses generated candidates.

- [ ] **Step 3: Implement assembly mapping**

For every section:

- map copy by `section_id`
- map selected or recommended image candidate by `slot_id`
- keep `source_type`, `identity_check`, and `candidate_id`
- mark missing image as `status = "missing_image"` instead of silently hiding it

- [ ] **Step 4: Run test and verify pass**

Run: `cd backend && uv run pytest tests/test_page_assembly_with_generated_assets.py -v`  
Expected: PASS.

### Task 5: QA가 이미지 누락과 상품 정체성 미검수를 차단

**Files:**
- Modify: `backend/src/agents/nodes/qa_review/agent.py`
- Test: `backend/tests/test_qa_blocks_missing_or_unreviewed_images.py`

- [ ] **Step 1: Write failing QA test**

```python
from backend.src.agents.nodes.qa_review.agent import QAReviewAgent
from backend.src.agents.state import AgentRunState


def test_qa_warns_when_product_image_identity_needs_review():
    state = AgentRunState(
        project_id="project-1",
        outputs={
            "page_assembly": {
                "sections": [
                    {
                        "section_id": "hero",
                        "visual_slot": {
                            "asset_id": "asset-real-hero",
                            "source_type": "real-generated",
                            "identity_check": {"status": "needs_review"},
                        },
                    }
                ]
            }
        },
    )

    result = QAReviewAgent().run(state)
    qa = result.outputs["qa_review"]

    assert qa["warnings"][0]["code"] == "IMAGE_IDENTITY_NEEDS_REVIEW"
    assert qa["can_export"] is False
```

- [ ] **Step 2: Run test and verify failure**

Run: `cd backend && uv run pytest tests/test_qa_blocks_missing_or_unreviewed_images.py -v`  
Expected: FAIL until QA blocks unreviewed images.

- [ ] **Step 3: Implement QA checks**

QA must block export when:

- required section has `missing_image`
- real-generated product image has `identity_check.status != "passed"`
- URL reference analysis reports high copy risk
- copy contains unsupported absolute claims

- [ ] **Step 4: Run QA tests**

Run: `cd backend && uv run pytest tests/test_qa_blocks_missing_or_unreviewed_images.py -v`  
Expected: PASS.

### Task 6: Frontend real image states and assembly warnings

**Files:**
- Modify: `frontend/src/components/GenerationProgressShell.tsx`
- Modify: `frontend/src/components/GeneratedDetailPageResult.tsx`
- Modify: `frontend/src/components/ReviewEditorLayout.tsx`

- [ ] **Step 1: Display real image state labels**

Frontend must display:

- `이미지 생성 비용 승인 필요`
- `이미지 생성 중`
- `상품 정체성 검수 필요`
- `상세페이지에 배치됨`
- `이미지 누락`

- [ ] **Step 2: Display QA blocking message**

If `qa_review.can_export === false`, result screen must show:

```text
출력 전 확인이 필요합니다
상품 이미지 검수 또는 누락된 이미지를 확인해 주세요.
```

- [ ] **Step 3: Run frontend build**

Run: `cd frontend && npm.cmd run build`  
Expected: PASS.

## Done Criteria

- Real image generation cannot happen without explicit approval.
- Image model/provider can be configured through `.env.example`.
- Upload/URL/reference images can be used as source candidates.
- Real-generated candidates are preserved with source and identity metadata.
- Page assembly maps selected generated images to sections.
- QA blocks export when image identity is unreviewed or required images are missing.
- Frontend shows seller-friendly Korean image states.
- Mock mode still never spends credits.

