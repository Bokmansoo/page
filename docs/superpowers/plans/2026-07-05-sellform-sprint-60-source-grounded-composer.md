# Sellform Sprint 60 Source-Grounded Detail Page Composer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사진 1장, 상품 URL, 자유 설명 중 하나만으로 시작하고, AI가 자료를 구조화한 뒤 사용자가 확인한 정보와 텍스트 레이어 기반 렌더러로 더 상업적인 상세페이지를 생성한다.

**Architecture:** 기존 agent pipeline의 `source_collection`, `reference_analysis`, `visual_planning`, `image_generation`, `ProductPage/PageSection`, Sprint 57 WYSIWYG export 경로를 유지한다. 새 작업은 원박스 입력 DTO, 입력 구조화/확인 API, 섹션별 visual strategy, no-text image policy, React text layer renderer 계약을 추가한다.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, pytest, Next.js 14, React, TypeScript, Playwright.

---

## Scope

- 첫 화면에서 사진, URL, 자유 설명 중 하나만 있어도 생성 시작 가능
- 자유 입력을 상품명/스펙/가격/배송/분위기/URL 후보로 구조화
- 생성 전 확인 화면에서 사용자가 사실과 이미지 후보를 확인
- 섹션별 이미지 전략을 `original_asset`, `cutout_composite`, `generated_scene`, `html_graphic`으로 명시
- 이미지 생성 프롬프트에 한글/영문/로고/워터마크 금지 정책 적용
- 모든 한글 문구는 React 텍스트 레이어로 렌더링
- 기존 WYSIWYG export 계획과 충돌하지 않고 final page DTO로 연결

## Non-Goals

- 모든 외부 쇼핑몰 URL의 완전 자동 수집 보장
- 인증서/공장 자료의 진위 자동 검증
- 사진 1장만으로 정확한 측면/후면/패키지 생성 보장
- 이미지 안에 텍스트를 직접 생성하는 방식
- 스마트스토어/쿠팡 자동 등록 고도화

## File Structure

- Create: `backend/src/services/intake_structuring_service.py`
  - 자유 입력과 기존 프로젝트 입력을 구조화된 초안 필드로 변환한다.
- Create: `backend/src/services/detail_page_scene_planner.py`
  - 확인된 사실과 이미지 후보를 바탕으로 섹션별 visual strategy와 image job policy를 생성한다.
- Modify: `backend/src/agents/nodes/source_collection/schema.py`
  - 자유 입력, 참고 URL, 입력 품질 요약 필드를 추가한다.
- Modify: `backend/src/agents/nodes/source_collection/agent.py`
  - 원박스 입력과 URL/업로드 이미지를 보존한다.
- Modify: `backend/src/agents/nodes/visual_planning/agent.py`
  - 섹션별 visual strategy와 no-text prompt 정책을 image_jobs에 포함한다.
- Modify: `backend/src/agents/nodes/image_generation/agent.py`
  - `text_free_required`, `visual_strategy`, `source_asset_ids`를 image candidate와 job report에 유지한다.
- Modify: `backend/src/api/agent_runs.py`
  - 원박스 입력 생성 요청과 구조화 확인 데이터를 받을 수 있게 한다.
- Create: `backend/tests/test_intake_structuring_service.py`
- Create: `backend/tests/test_detail_page_scene_planner.py`
- Modify: `backend/tests/test_source_collection_agent.py`
- Modify: `backend/tests/test_real_multimodal_image_generation_contract.py`
- Modify: `frontend/src/components/AIDetailPageIntake.tsx`
  - 큰 자유 입력창, 사진 업로드, 선택 고급 입력 UI를 제공한다.
- Create: `frontend/src/components/StructuredIntakeReview.tsx`
  - AI가 구조화한 상품명/특징/스펙/이미지 후보를 생성 전 확인한다.
- Modify: `frontend/src/components/GeneratedDetailPageResult.tsx`
  - 이미지 출처와 visual strategy를 표시하고 텍스트 레이어 원칙을 유지한다.
- Modify: `frontend/src/lib/api.ts`
  - structured intake review API 타입을 추가한다.
- Create: `frontend/e2e/source-grounded-composer.spec.ts`

## Data Contracts

### One Box Intake Request

```json
{
  "freeform_input": "아이용 자전거입니다. LED 조명이 있고 보조바퀴 탈착 가능해요.",
  "product_name": "",
  "description": "",
  "product_url": "",
  "reference_urls": [],
  "desired_mood": "",
  "asset_ids": []
}
```

### Structured Intake Draft

```json
{
  "product_name": {
    "value": "아이용 LED 자전거",
    "source": "freeform_input",
    "confidence": "needs_review"
  },
  "selling_points": [
    {
      "text": "LED 조명",
      "source": "freeform_input",
      "confidence": "confirmed"
    }
  ],
  "price": {
    "value": "39,900원",
    "source": "freeform_input",
    "confidence": "needs_review"
  },
  "desired_mood": ["안전함", "감성적"],
  "warnings": []
}
```

### Section Scene Plan

```json
{
  "sections": [
    {
      "section_id": "hero",
      "section_type": "hero",
      "visual_strategy": "cutout_composite",
      "source_asset_ids": ["asset-1"],
      "image_prompt": "Premium product studio background with soft shadows. No text, no Korean letters, no English letters, no logo, no watermark.",
      "text_free_required": true,
      "identity_risk": "medium"
    },
    {
      "section_id": "spec_table",
      "section_type": "spec_table",
      "visual_strategy": "html_graphic",
      "source_asset_ids": [],
      "image_prompt": "",
      "text_free_required": true,
      "identity_risk": "low"
    }
  ]
}
```

## Tasks

### Task 1: 원박스 입력 구조화 서비스

**Files:**
- Create: `backend/src/services/intake_structuring_service.py`
- Create: `backend/tests/test_intake_structuring_service.py`

- [ ] **Step 1: Write failing tests for freeform parsing**

Create `backend/tests/test_intake_structuring_service.py`:

```python
from src.services.intake_structuring_service import structure_intake


def test_structure_intake_extracts_basic_fields_from_freeform_text():
    draft = structure_intake(
        {
            "freeform_input": "아이용 자전거입니다. LED 조명이 있고 보조바퀴 탈착 가능해요. 가격은 39,900원이고 무료배송입니다. 안전하고 감성적인 느낌으로 만들어주세요.",
            "product_name": "",
            "description": "",
            "product_url": "",
            "reference_urls": [],
            "desired_mood": "",
            "asset_ids": [],
        }
    )

    assert draft["product_name"]["value"] == "아이용 자전거"
    assert {"text": "LED 조명", "source": "freeform_input", "confidence": "needs_review"} in draft["selling_points"]
    assert {"text": "보조바퀴 탈착 가능", "source": "freeform_input", "confidence": "needs_review"} in draft["selling_points"]
    assert draft["price"]["value"] == "39,900원"
    assert draft["shipping"]["value"] == "무료배송"
    assert "안전함" in draft["desired_mood"]
    assert "감성적" in draft["desired_mood"]


def test_structure_intake_prefers_explicit_fields_over_freeform_guess():
    draft = structure_intake(
        {
            "freeform_input": "아이용 자전거입니다. 가격은 39,900원입니다.",
            "product_name": "베이비 라이트 밸런스 바이크",
            "description": "LED 라이트와 탈착식 보조바퀴가 있는 유아용 자전거",
            "product_url": "https://example.com/products/bike",
            "reference_urls": ["https://example.com/reference"],
            "desired_mood": "프리미엄, 안전함",
            "asset_ids": ["asset-1"],
        }
    )

    assert draft["product_name"] == {
        "value": "베이비 라이트 밸런스 바이크",
        "source": "explicit_field",
        "confidence": "confirmed",
    }
    assert draft["product_url"]["value"] == "https://example.com/products/bike"
    assert draft["reference_urls"] == ["https://example.com/reference"]
    assert "프리미엄" in draft["desired_mood"]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```cmd
cd /d C:\page\backend
uv run pytest tests\test_intake_structuring_service.py -v
```

Expected: FAIL because `src.services.intake_structuring_service` does not exist.

- [ ] **Step 3: Implement deterministic structuring helper**

Create `backend/src/services/intake_structuring_service.py`:

```python
import re
from typing import Any


def _field(value: str, source: str, confidence: str) -> dict[str, str]:
    return {"value": value.strip(), "source": source, "confidence": confidence}


def _extract_price(text: str) -> str:
    match = re.search(r"(\d{1,3}(?:,\d{3})+|\d+)\s*원", text)
    return f"{match.group(1)}원" if match else ""


def _extract_product_name(text: str) -> str:
    normalized = text.strip()
    match = re.search(r"([가-힣A-Za-z0-9\s]+?)(?:입니다|이에요|예요)", normalized)
    if match:
        return match.group(1).strip()
    first_sentence = re.split(r"[.!?\n]", normalized, maxsplit=1)[0].strip()
    return first_sentence[:40]


def _extract_selling_points(text: str) -> list[dict[str, str]]:
    candidates = []
    rules = [
        ("LED", "LED 조명"),
        ("보조바퀴", "보조바퀴 탈착 가능" if "탈착" in text else "보조바퀴"),
        ("탈착", "탈착 가능"),
        ("무료배송", "무료배송"),
    ]
    seen = set()
    for needle, label in rules:
        if needle in text and label not in seen:
            candidates.append({"text": label, "source": "freeform_input", "confidence": "needs_review"})
            seen.add(label)
    return candidates


def _extract_mood(text: str, explicit: str = "") -> list[str]:
    source = f"{explicit}, {text}"
    mood_map = {
        "안전": "안전함",
        "감성": "감성적",
        "프리미엄": "프리미엄",
        "고급": "고급스러움",
        "미니멀": "미니멀",
        "자연": "내추럴",
    }
    moods = []
    for needle, label in mood_map.items():
        if needle in source and label not in moods:
            moods.append(label)
    return moods


def structure_intake(payload: dict[str, Any]) -> dict[str, Any]:
    freeform = str(payload.get("freeform_input") or "")
    explicit_name = str(payload.get("product_name") or "").strip()
    description = str(payload.get("description") or "").strip()
    desired_mood = str(payload.get("desired_mood") or "").strip()
    product_url = str(payload.get("product_url") or "").strip()
    reference_urls = [str(url).strip() for url in payload.get("reference_urls") or [] if str(url).strip()]

    product_name = (
        _field(explicit_name, "explicit_field", "confirmed")
        if explicit_name
        else _field(_extract_product_name(freeform), "freeform_input", "needs_review")
    )
    price = _extract_price(freeform)
    shipping_value = "무료배송" if "무료배송" in freeform else ""

    selling_points = _extract_selling_points(f"{description}\n{freeform}")
    if description:
        selling_points.append({"text": description, "source": "explicit_field", "confidence": "confirmed"})

    return {
        "product_name": product_name,
        "description": _field(description, "explicit_field", "confirmed") if description else _field("", "", "missing"),
        "product_url": _field(product_url, "explicit_field", "confirmed") if product_url else _field("", "", "missing"),
        "reference_urls": reference_urls,
        "selling_points": selling_points,
        "price": _field(price, "freeform_input", "needs_review") if price else _field("", "", "missing"),
        "shipping": _field(shipping_value, "freeform_input", "needs_review") if shipping_value else _field("", "", "missing"),
        "desired_mood": _extract_mood(freeform, desired_mood),
        "asset_ids": list(payload.get("asset_ids") or []),
        "warnings": [],
    }
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```cmd
cd /d C:\page\backend
uv run pytest tests\test_intake_structuring_service.py -v
```

Expected: PASS.

### Task 2: Source collection schema 확장

**Files:**
- Modify: `backend/src/agents/nodes/source_collection/schema.py`
- Modify: `backend/src/agents/nodes/source_collection/agent.py`
- Modify: `backend/tests/test_source_collection_agent.py`

- [ ] **Step 1: Add failing source collection test**

Append to `backend/tests/test_source_collection_agent.py`:

```python
def test_source_collection_preserves_freeform_and_reference_urls():
    from src.agents.nodes.source_collection.agent import SourceCollectionAgent
    from src.agents.state import AgentRunState, ProductInput

    state = AgentRunState(
        project_id="project-1",
        product_input=ProductInput(
            product_name="",
            description="",
            product_url="https://example.com/product",
            asset_ids=["asset-1"],
            reference_urls=["https://example.com/reference"],
            freeform_input="아이용 자전거입니다. LED 조명이 있습니다.",
        ),
    )

    result = SourceCollectionAgent().run(state)
    output = result.outputs["source_collection"]

    assert output["product_url"] == "https://example.com/product"
    assert output["reference_urls"] == ["https://example.com/reference"]
    assert output["freeform_input"] == "아이용 자전거입니다. LED 조명이 있습니다."
    assert output["source_summary"]["has_freeform_input"] is True
```

- [ ] **Step 2: Run source collection tests and verify failure**

Run:

```cmd
cd /d C:\page\backend
uv run pytest tests\test_source_collection_agent.py -v
```

Expected: FAIL because `freeform_input`, `reference_urls`, or `has_freeform_input` is missing.

- [ ] **Step 3: Extend schema**

Modify `backend/src/agents/nodes/source_collection/schema.py`:

```python
class SourceSummary(BaseModel):
    has_uploaded_image: bool = False
    has_product_url: bool = False
    has_freeform_input: bool = False
    has_reference_url: bool = False
    primary_visual_source: Literal["uploaded", "url", "none"] = "none"


class SourceCollectionOutput(BaseModel):
    product_url: str = ""
    freeform_input: str = ""
    reference_urls: list[str] = Field(default_factory=list)
    uploaded_images: list[CollectedImageSource] = Field(default_factory=list)
    url_images: list[CollectedImageSource] = Field(default_factory=list)
    reference_text_blocks: list[str] = Field(default_factory=list)
    source_summary: SourceSummary = Field(default_factory=SourceSummary)
```

- [ ] **Step 4: Preserve fields in agent output**

Modify `backend/src/agents/nodes/source_collection/agent.py` so the output includes:

```python
"freeform_input": getattr(state.product_input, "freeform_input", "") or "",
"reference_urls": getattr(state.product_input, "reference_urls", []) or [],
"source_summary": {
    "has_uploaded_image": bool(uploaded_images),
    "has_product_url": bool(state.product_input.product_url),
    "has_freeform_input": bool(getattr(state.product_input, "freeform_input", "") or ""),
    "has_reference_url": bool(getattr(state.product_input, "reference_urls", []) or []),
    "primary_visual_source": primary,
},
```

- [ ] **Step 5: Run source collection tests**

Run:

```cmd
cd /d C:\page\backend
uv run pytest tests\test_source_collection_agent.py -v
```

Expected: PASS.

### Task 3: 섹션별 장면 계획 서비스

**Files:**
- Create: `backend/src/services/detail_page_scene_planner.py`
- Create: `backend/tests/test_detail_page_scene_planner.py`

- [ ] **Step 1: Write failing scene planner tests**

Create `backend/tests/test_detail_page_scene_planner.py`:

```python
from src.services.detail_page_scene_planner import build_scene_plan


def test_scene_plan_uses_composite_for_hero_when_product_asset_exists():
    plan = build_scene_plan(
        product_name="아이용 LED 자전거",
        asset_ids=["asset-1"],
        confirmed_facts=["LED 조명", "보조바퀴 탈착 가능"],
        desired_mood=["안전함", "감성적"],
    )

    hero = next(section for section in plan["sections"] if section["section_id"] == "hero")
    assert hero["visual_strategy"] == "cutout_composite"
    assert hero["source_asset_ids"] == ["asset-1"]
    assert hero["text_free_required"] is True
    assert "No text" in hero["image_prompt"]
    assert "no Korean letters" in hero["image_prompt"]


def test_scene_plan_keeps_spec_table_as_html_graphic():
    plan = build_scene_plan(
        product_name="아이용 LED 자전거",
        asset_ids=["asset-1"],
        confirmed_facts=["LED 조명"],
        desired_mood=[],
    )

    spec = next(section for section in plan["sections"] if section["section_id"] == "spec_table")
    assert spec["visual_strategy"] == "html_graphic"
    assert spec["image_prompt"] == ""
    assert spec["identity_risk"] == "low"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```cmd
cd /d C:\page\backend
uv run pytest tests\test_detail_page_scene_planner.py -v
```

Expected: FAIL because service does not exist.

- [ ] **Step 3: Implement scene planner**

Create `backend/src/services/detail_page_scene_planner.py`:

```python
TEXT_FREE_POLICY = "No text, no Korean letters, no English letters, no logo, no watermark, no label."


def _prompt(base: str) -> str:
    return f"{base} {TEXT_FREE_POLICY} Leave clean space for typography."


def build_scene_plan(
    *,
    product_name: str,
    asset_ids: list[str],
    confirmed_facts: list[str],
    desired_mood: list[str],
) -> dict:
    mood_text = ", ".join(desired_mood) if desired_mood else "clean commerce"
    primary_assets = asset_ids[:1]

    sections = [
        {
            "section_id": "hero",
            "section_type": "hero",
            "visual_strategy": "cutout_composite" if primary_assets else "generated_scene",
            "source_asset_ids": primary_assets,
            "image_prompt": _prompt(
                f"Premium commerce hero background for {product_name}, {mood_text}, studio lighting, realistic shadows."
            ),
            "text_free_required": True,
            "identity_risk": "medium" if primary_assets else "high",
        },
        {
            "section_id": "pain_points",
            "section_type": "pain_points",
            "visual_strategy": "html_graphic",
            "source_asset_ids": [],
            "image_prompt": "",
            "text_free_required": True,
            "identity_risk": "low",
        },
        {
            "section_id": "benefits",
            "section_type": "benefit_cards",
            "visual_strategy": "html_graphic",
            "source_asset_ids": [],
            "image_prompt": "",
            "text_free_required": True,
            "identity_risk": "low",
        },
        {
            "section_id": "lifestyle",
            "section_type": "lifestyle_scene",
            "visual_strategy": "cutout_composite" if primary_assets else "generated_scene",
            "source_asset_ids": primary_assets,
            "image_prompt": _prompt(
                f"Natural lifestyle scene for {product_name}, {mood_text}, commercial product photography."
            ),
            "text_free_required": True,
            "identity_risk": "medium" if primary_assets else "high",
        },
        {
            "section_id": "spec_table",
            "section_type": "spec_table",
            "visual_strategy": "html_graphic",
            "source_asset_ids": [],
            "image_prompt": "",
            "text_free_required": True,
            "identity_risk": "low",
        },
    ]

    return {
        "product_name": product_name,
        "confirmed_fact_count": len(confirmed_facts),
        "sections": sections,
    }
```

- [ ] **Step 4: Run scene planner tests**

Run:

```cmd
cd /d C:\page\backend
uv run pytest tests\test_detail_page_scene_planner.py -v
```

Expected: PASS.

### Task 4: Visual planning image job contract 확장

**Files:**
- Modify: `backend/src/agents/nodes/visual_planning/agent.py`
- Modify: `backend/tests/test_real_multimodal_image_generation_contract.py`

- [ ] **Step 1: Add failing visual planning contract test**

Append to `backend/tests/test_real_multimodal_image_generation_contract.py`:

```python
def test_visual_planning_marks_generated_jobs_as_text_free():
    from src.agents.nodes.visual_planning.agent import VisualPlanningAgent
    from src.agents.state import AgentRunState, ProductInput

    state = AgentRunState(
        project_id="project-1",
        product_input=ProductInput(
            product_name="아이용 LED 자전거",
            description="LED 조명과 보조바퀴",
            asset_ids=["asset-1"],
        ),
    )

    result = VisualPlanningAgent().run(state)
    jobs = result.outputs["visual_planning"]["image_jobs"]

    assert jobs
    assert all(job["text_free_required"] is True for job in jobs)
    assert all("No text" in job["prompt"] for job in jobs)
    assert all("no Korean letters" in job["prompt"] for job in jobs)
```

- [ ] **Step 2: Run test and verify failure**

Run:

```cmd
cd /d C:\page\backend
uv run pytest tests\test_real_multimodal_image_generation_contract.py::test_visual_planning_marks_generated_jobs_as_text_free -v
```

Expected: FAIL because `text_free_required` is not present.

- [ ] **Step 3: Add text-free policy to visual planning jobs**

In `backend/src/agents/nodes/visual_planning/agent.py`, add a module-level constant:

```python
TEXT_FREE_IMAGE_POLICY = "No text, no Korean letters, no English letters, no logo, no watermark, no label."
```

When building each image job in `_attach_image_jobs`, append the policy to `prompt` and add contract fields:

```python
raw_prompt = self._prompt_for_slot(
    product_name=product_name,
    slot_id=slot_id,
    visual_plan=visual_plan,
    page_plan=page_plan,
    copy_set=copy_set,
)
prompt = f"{raw_prompt} {TEXT_FREE_IMAGE_POLICY} Leave clean space for HTML typography."
```

Then include:

```python
"prompt": prompt,
"text_free_required": True,
"visual_strategy": "cutout_composite" if state.product_input.asset_ids else "generated_scene",
"source_asset_ids": state.product_input.asset_ids or [],
```

- [ ] **Step 4: Run contract test**

Run:

```cmd
cd /d C:\page\backend
uv run pytest tests\test_real_multimodal_image_generation_contract.py::test_visual_planning_marks_generated_jobs_as_text_free -v
```

Expected: PASS.

### Task 5: 원박스 입력 UI와 구조화 확인 화면

**Files:**
- Modify: `frontend/src/components/AIDetailPageIntake.tsx`
- Create: `frontend/src/components/StructuredIntakeReview.tsx`
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/e2e/source-grounded-composer.spec.ts`

- [ ] **Step 1: Write failing E2E for one-box input**

Create `frontend/e2e/source-grounded-composer.spec.ts`:

```ts
import { test, expect } from "@playwright/test";

test("one-box intake lets seller start with photo and freeform text", async ({ page }) => {
  await page.route("**/api/agent-runs/structure-intake", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        product_name: { value: "아이용 LED 자전거", source: "freeform_input", confidence: "needs_review" },
        selling_points: [
          { text: "LED 조명", source: "freeform_input", confidence: "needs_review" },
          { text: "보조바퀴 탈착 가능", source: "freeform_input", confidence: "needs_review" },
        ],
        price: { value: "39,900원", source: "freeform_input", confidence: "needs_review" },
        shipping: { value: "무료배송", source: "freeform_input", confidence: "needs_review" },
        desired_mood: ["안전함", "감성적"],
        warnings: [],
      }),
    });
  });

  await page.goto("/workspace");
  await page.getByLabel("상품 자료").fill("아이용 자전거입니다. LED 조명이 있고 보조바퀴 탈착 가능해요. 가격은 39,900원이고 무료배송입니다.");
  await page.getByRole("button", { name: "자료 확인하기" }).click();

  await expect(page.getByText("AI가 이렇게 이해했어요")).toBeVisible();
  await expect(page.getByDisplayValue("아이용 LED 자전거")).toBeVisible();
  await expect(page.getByText("LED 조명")).toBeVisible();
  await expect(page.getByText("보조바퀴 탈착 가능")).toBeVisible();
});
```

- [ ] **Step 2: Run E2E and verify failure**

Run:

```cmd
cd /d C:\page\frontend
npm.cmd test -- source-grounded-composer.spec.ts
```

Expected: FAIL because the UI and endpoint do not exist.

- [ ] **Step 3: Add API helper**

Modify `frontend/src/lib/api.ts`:

```ts
export type StructuredIntakeDraft = {
  product_name: { value: string; source: string; confidence: string };
  selling_points: Array<{ text: string; source: string; confidence: string }>;
  price?: { value: string; source: string; confidence: string };
  shipping?: { value: string; source: string; confidence: string };
  desired_mood: string[];
  warnings: string[];
};

export async function structureIntake(payload: {
  freeform_input: string;
  product_name?: string;
  description?: string;
  product_url?: string;
  reference_urls?: string[];
  desired_mood?: string;
  asset_ids?: string[];
}): Promise<StructuredIntakeDraft> {
  const res = await fetch(apiUrl("/api/agent-runs/structure-intake"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error("상품 자료를 정리하지 못했습니다.");
  }
  return res.json();
}
```

- [ ] **Step 4: Add review component**

Create `frontend/src/components/StructuredIntakeReview.tsx`:

```tsx
"use client";

import type { StructuredIntakeDraft } from "@/lib/api";

type Props = {
  draft: StructuredIntakeDraft;
  onBack: () => void;
  onConfirm: () => void;
};

export default function StructuredIntakeReview({ draft, onBack, onConfirm }: Props) {
  return (
    <section className="w-full max-w-3xl rounded-2xl border border-emerald-100 bg-white p-6 shadow-sm">
      <div className="mb-5">
        <p className="text-sm font-semibold text-emerald-700">AI가 이렇게 이해했어요</p>
        <h2 className="mt-1 text-2xl font-bold text-slate-950">생성 전에 상품 정보를 확인해주세요</h2>
      </div>

      <label className="block text-sm font-semibold text-slate-700">
        상품명
        <input
          className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 text-sm"
          defaultValue={draft.product_name.value}
        />
      </label>

      <div className="mt-5">
        <p className="text-sm font-semibold text-slate-700">핵심 특징</p>
        <div className="mt-2 space-y-2">
          {draft.selling_points.map((point) => (
            <label key={point.text} className="flex items-center gap-3 rounded-xl border border-slate-200 px-4 py-3 text-sm">
              <input type="checkbox" defaultChecked className="h-4 w-4 accent-emerald-600" />
              <span className="font-medium text-slate-900">{point.text}</span>
              <span className="ml-auto text-xs text-slate-500">{point.confidence === "confirmed" ? "확실함" : "확인 필요"}</span>
            </label>
          ))}
        </div>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="block text-sm font-semibold text-slate-700">
          가격
          <input className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 text-sm" defaultValue={draft.price?.value ?? ""} />
        </label>
        <label className="block text-sm font-semibold text-slate-700">
          배송
          <input className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 text-sm" defaultValue={draft.shipping?.value ?? ""} />
        </label>
      </div>

      <div className="mt-6 flex justify-end gap-3">
        <button type="button" onClick={onBack} className="rounded-xl border border-slate-200 px-5 py-3 text-sm font-semibold text-slate-700">
          다시 입력
        </button>
        <button type="button" onClick={onConfirm} className="rounded-xl bg-emerald-600 px-5 py-3 text-sm font-bold text-white">
          이 정보로 상세페이지 만들기
        </button>
      </div>
    </section>
  );
}
```

- [ ] **Step 5: Update intake component**

Modify `frontend/src/components/AIDetailPageIntake.tsx` so the primary form has:

```tsx
<label className="block text-sm font-semibold text-slate-700" htmlFor="freeform-input">
  상품 자료
</label>
<textarea
  id="freeform-input"
  aria-label="상품 자료"
  value={freeformInput}
  onChange={(event) => setFreeformInput(event.target.value)}
  placeholder="상품 설명, URL, 스펙, 가격, 원하는 분위기를 자유롭게 붙여넣으세요."
  rows={6}
  className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm"
/>
<button type="button" onClick={handleStructureIntake}>
  자료 확인하기
</button>
```

When `structuredDraft` exists, render:

```tsx
<StructuredIntakeReview
  draft={structuredDraft}
  onBack={() => setStructuredDraft(null)}
  onConfirm={handleSubmitConfirmedDraft}
/>
```

- [ ] **Step 6: Run E2E**

Run:

```cmd
cd /d C:\page\frontend
npm.cmd test -- source-grounded-composer.spec.ts
```

Expected: PASS.

### Task 6: API endpoint for structured intake

**Files:**
- Modify: `backend/src/api/agent_runs.py`
- Test: `backend/tests/test_intake_structuring_service.py`

- [ ] **Step 1: Add API test**

Append to `backend/tests/test_intake_structuring_service.py`:

```python
def test_structure_intake_api(client, auth_headers):
    response = client.post(
        "/api/agent-runs/structure-intake",
        json={
            "freeform_input": "아이용 자전거입니다. LED 조명이 있습니다. 가격은 39,900원입니다.",
            "asset_ids": [],
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["product_name"]["value"] == "아이용 자전거"
    assert data["price"]["value"] == "39,900원"
```

- [ ] **Step 2: Run API test and verify failure**

Run:

```cmd
cd /d C:\page\backend
uv run pytest tests\test_intake_structuring_service.py::test_structure_intake_api -v
```

Expected: FAIL with 404.

- [ ] **Step 3: Add endpoint**

Modify `backend/src/api/agent_runs.py`:

```python
from src.services.intake_structuring_service import structure_intake


@router.post("/structure-intake")
def structure_agent_intake(payload: dict):
    return structure_intake(payload)
```

If the file uses a different router prefix pattern, add this endpoint to the existing agent runs router so the full path is `/api/agent-runs/structure-intake`.

- [ ] **Step 4: Run API test**

Run:

```cmd
cd /d C:\page\backend
uv run pytest tests\test_intake_structuring_service.py::test_structure_intake_api -v
```

Expected: PASS.

### Task 7: Full contract verification

**Files:**
- Existing tests only

- [ ] **Step 1: Run backend focused tests**

Run:

```cmd
cd /d C:\page\backend
uv run pytest tests\test_intake_structuring_service.py tests\test_detail_page_scene_planner.py tests\test_source_collection_agent.py tests\test_real_multimodal_image_generation_contract.py -v
```

Expected: PASS.

- [ ] **Step 2: Run frontend focused tests**

Run:

```cmd
cd /d C:\page\frontend
npm.cmd test -- source-grounded-composer.spec.ts
```

Expected: PASS.

- [ ] **Step 3: Run WYSIWYG/export regression tests**

Run the Sprint 57 tests after that sprint has landed:

```cmd
cd /d C:\page\backend
uv run pytest tests\test_wysiwyg_export_contract.py -v
```

Expected: PASS. The source-grounded composer must feed the same canonical renderer/export path.

## Acceptance Criteria

- 사진 1장, URL 1개, 자유 설명 중 하나만 있어도 사용자가 시작할 수 있다.
- 자유 입력은 상품명, 특징, 가격, 배송, 분위기 후보로 구조화된다.
- 생성 전 확인 화면에서 사용자가 AI가 이해한 내용을 칸칸이 확인할 수 있다.
- 이미지 생성 job은 `text_free_required=true`와 no-text prompt policy를 가진다.
- 섹션별 visual strategy가 저장되어 결과 화면과 export에서 추적 가능하다.
- 한글 제목, 본문, 스펙, CTA는 이미지 안에 생성되지 않고 React 텍스트 레이어로 렌더링된다.
- WYSIWYG export는 Sprint 57 canonical renderer를 계속 사용한다.

## Rollout Notes

- 기존 `/workspace` 시작 화면은 갑자기 복잡해지면 안 된다. 첫 화면은 큰 입력창과 업로드 중심으로 유지한다.
- "더 정확하게 만들기"는 접힌 고급 영역으로 제공한다.
- 사용자가 사진 1장만 넣은 경우 결과 화면에 "추가 사진이나 URL을 넣으면 더 정확해집니다" 안내를 보여준다.
- URL 수집 실패는 생성 실패가 아니라 "수집하지 못한 자료" 경고로 처리한다.

