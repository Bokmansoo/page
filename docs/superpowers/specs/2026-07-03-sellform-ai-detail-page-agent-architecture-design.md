# Sellform Final Design: AI Detail Page Generation Agent

> Status: Final planning draft from product interview on 2026-07-03  
> Scope: Reframe Sellform from an editor-first workspace into an AI detail page generation service  
> Core decision: Build the product around an agentic generation pipeline, not around the downstream page editor.

## 1. Product Definition

Sellform is an AI detail page generation service for solo sellers.

The user should be able to provide a product photo, product URL, product name, short description, or any combination of those inputs. Sellform then understands the product, decides how it should be sold, writes the detail page copy, plans the necessary visuals, generates or edits images, assembles a long mobile detail page, and lets the seller review and export the result.

The final product is not primarily:

- a Figma exporter
- a manual template editor
- a marketplace registration form
- a generic image generator

Those are supporting outputs. The main promise is:

**상품 자료를 넣으면 AI가 팔릴 만한 상세페이지를 기획하고 만들어준다.**

## 2. Target User

The primary user is a solo seller who has a product but does not know how to present it.

Typical user thoughts:

- "상세페이지를 어떤 순서로 구성해야 할지 모르겠다."
- "이 상품의 장점을 어떻게 써야 사람들이 사고 싶어질지 모르겠다."
- "사진은 있는데 배경이나 연출을 어떻게 해야 할지 모르겠다."
- "스마트스토어에 올리고 싶은데 상품명, 태그, 상세페이지, 이미지가 막막하다."
- "디자이너나 마케터 없이 혼자서 판매 가능한 수준까지 만들고 싶다."

Sellform should feel like an AI MD who helps the seller make decisions, not like a blank design tool.

## 3. Final User Experience

The final experience should resemble the 19-reference-image flow the user provided:

1. The seller starts from a simple AI detail page creation screen.
2. The seller uploads product photos or enters a URL/product name.
3. AI analyzes the product and shows what it understood.
4. AI recommends sales directions and lets the seller confirm or adjust.
5. AI proposes selling points, section flow, and visual direction.
6. AI generates or prepares required images with explicit cost approval.
7. The seller reviews generated/selected images.
8. Sellform assembles a long mobile detail page.
9. The seller edits copy, images, or sections with AI commands.
10. The seller exports PNG, Figma, copy set, and marketplace-ready data.

The first successful moment should not be "I opened an editor."  
It should be:

**"AI가 내 상품을 이해했고, 판매 방향과 상세페이지 초안을 만들어줬다."**

## 4. Current Structure Problem

The current implementation has many useful pieces, but the product center is wrong.

Current center:

```text
workspace -> project -> facts/style/page editor -> visual package -> export
```

This exposes downstream machinery too early. The user sees an editor with empty visual slots before experiencing the main AI value.

Target center:

```text
product input -> AI generation pipeline -> complete detail page draft -> review editor -> export/register
```

The existing editor should become the review and refinement stage after generation, not the first product surface.

## 5. Recommended Architecture

Use an agentic pipeline with explicit state transitions.

LangGraph or a LangGraph-like state graph is recommended because this product is not a single LLM call. It has branching, retries, user confirmations, cost approvals, mock/real execution modes, and quality gates.

Recommended generation state:

```text
intake
  -> product_understanding
  -> missing_info_check
  -> sales_strategy
  -> user_strategy_confirmation
  -> page_planning
  -> copy_generation
  -> visual_planning
  -> image_cost_approval
  -> image_generation
  -> image_review
  -> page_assembly
  -> qa_review
  -> review_editor
  -> export_package
```

Each state must be persisted on the project so the user can leave, return, retry a failed step, or continue in mock mode.

## 6. Agent Roles

Sellform should not use one large prompt that says "make a detail page." It should separate responsibilities.

### 6.1 Product Understanding Agent

Input:

- uploaded product photos
- URL-collected product information
- user-entered product name or description
- optional competitor/reference links

Output:

- product type
- target customer
- buyer problem
- buyer hesitation
- verified facts
- inferred assumptions
- prohibited or risky claims
- representative image candidates

This agent must separate verified facts from guesses.

### 6.2 Sales Strategy Agent

Input:

- product understanding result
- seller goal
- marketplace context
- category hints

Output:

- one recommended sales direction
- two alternative directions
- main claim
- supporting claims
- emotional tone
- proof strategy
- reason why the recommendation fits

Example directions:

- problem-solving direction
- lifestyle/emotional direction
- spec/trust direction

### 6.3 Detail Page Planning Agent

Input:

- selected sales direction
- product facts
- target customer

Output:

- detail page section order
- section purpose
- section copy intent
- visual role per section
- required fact IDs per section

Default persuasive structure:

1. Problem statement
2. Main selling point
3. Supporting benefit
4. Reinforced proof or use scene
5. Remaining benefits
6. One-sentence summary
7. Product information and purchase decision details

This structure should adapt by category. A kids product, home appliance, food item, fashion product, and digital accessory should not share the exact same page flow.

### 6.4 Copywriting Agent

Input:

- page plan
- verified facts
- selected tone

Output:

- hero headline
- hero subcopy
- section title
- body copy
- captions
- badges
- FAQ copy
- product information copy
- CTA
- Smartstore title
- search tags
- SEO title and description

Copy must stay grounded in verified or user-approved facts. Unverified claims must be avoided or marked for review.

### 6.5 Visual Planning Agent

Input:

- page plan
- copy set
- product identity
- selected images

Output:

- visual roles
- image prompts
- reference image requirements
- product identity preservation rules
- background/style direction
- per-image cost estimate

Visual roles can include:

- representative product cut
- background-removed product cut
- lifestyle usage scene
- problem statement scene
- benefit visual
- detail close-up
- comparison table
- before/after visual
- icon or badge set
- mid-page CTA visual

### 6.6 Image Generation Agent

Input:

- visual plan
- approved image generation jobs
- product reference images

Output:

- generated image assets
- edited image assets
- failed jobs with reasons
- fallback asset recommendations

Rules:

- Product identity must be preserved for product-containing images.
- Real product images should be edited with reference-image generation where possible.
- Marketing copy, prices, certification marks, and logos should remain editable page layers instead of being baked into generated images.
- Paid generation must require explicit cost approval.
- Mock mode must produce deterministic placeholder assets without spending credits.

### 6.7 Assembly Agent

Input:

- page plan
- copy set
- approved visual assets
- selected template/layout rules

Output:

- complete long mobile detail page draft
- section-to-asset mapping
- page version
- export readiness checklist

The page should show actual copy and visual sections, not empty placeholders.

### 6.8 QA Agent

Input:

- assembled page
- copy set
- visual assets
- compliance rules

Output:

- missing image warnings
- unverified claim warnings
- exaggerated expression warnings
- marketplace readiness issues
- export blockers
- suggested fixes

QA should run before final export.

## 7. Prompt System Design

Prompting should be versioned and contract-driven.

Recommended prompt modules:

```text
prompts/
  system/
    sellform_agent_base.md
    commerce_claim_safety.md
    product_identity_safety.md
  agents/
    product_understanding.md
    sales_strategy.md
    page_planning.md
    copywriting.md
    visual_planning.md
    qa_review.md
  schemas/
    product_understanding.schema.json
    sales_strategy.schema.json
    page_plan.schema.json
    copy_set.schema.json
    visual_plan.schema.json
    qa_report.schema.json
```

The system prompts should define:

- Sellform's role as an AI MD for solo sellers
- fact grounding rules
- marketplace-safe copy rules
- image generation safety rules
- JSON output requirements
- Korean commerce copy tone
- refusal or fallback behavior when information is insufficient

The user-facing UI should not expose raw prompts. It should expose understandable steps like "상품 분석 중", "판매 방향 생성 중", and "상세페이지 조립 중".

## 8. Data Contracts

The pipeline should produce structured data that the frontend can render and the editor can modify.

Core entities:

- `ProductInput`
- `ProductUnderstanding`
- `SalesDirection`
- `SalesStrategySet`
- `DetailPagePlan`
- `CopySet`
- `VisualPlan`
- `ImageGenerationJob`
- `GeneratedAsset`
- `PageAssembly`
- `QAReport`
- `ExportPackage`

Every generated section should keep references:

- `section_id`
- `section_role`
- `copy_ids`
- `fact_ids`
- `visual_role`
- `image_asset_id`
- `claim_risk_level`

This makes the page editable, auditable, and exportable.

## 9. Mock Mode And Real Mode

Sellform must support two execution modes.

### Mock Mode

Used for development, demos, and no-credit testing.

- deterministic product understanding samples
- deterministic sales strategies
- placeholder image assets
- no external LLM or image API calls
- visible "mock mode" indicator for developers

### Real Mode

Used when API keys and cost approval are available.

- real LLM calls
- real vision/image analysis
- real image generation or image editing
- cost tracking
- retries and provider fallbacks
- error reporting

The user explicitly asked to avoid accidental credit usage during planning and testing. Therefore the product must default to mock mode in local development unless real mode is intentionally enabled.

## 10. Frontend UX Direction

The UI should move from a dark technical editor to a light AI creation flow.

### 10.1 Start Screen

Primary message:

**상품 사진이나 URL을 넣으면 AI가 상세페이지를 만들어드려요.**

Input options:

- product photo upload
- product URL
- product name
- short description
- optional reference link/image

Primary CTA:

**AI 상세페이지 만들기**

### 10.2 Generation Progress Screen

Show clear steps:

- 상품 이해
- 판매 방향 추천
- 상세페이지 구조 설계
- 문구 생성
- 이미지 연출 기획
- 이미지 생성
- 상세페이지 조립
- 검수

This screen should feel like the 19-image reference flow: the seller sees progress, not a blank editor.

### 10.3 Confirmation Screen

Before spending image credits or assembling the final page, show:

- AI understanding card
- recommended sales direction
- selected product images
- expected visual jobs
- estimated cost

Actions:

- "이 방향으로 생성"
- "다른 방향 보기"
- "조금 수정하기"

### 10.4 Generated Detail Page Review

After generation, show:

- center: long mobile detail page preview
- left: strategy and section outline
- right: AI edit commands and selected section properties

The editor is a review/refinement tool, not the starting point.

### 10.5 Output Screen

Output package:

- long PNG
- editable web page
- Figma export
- copy set
- image assets
- marketplace data

## 11. Backend Service Direction

Recommended backend modules:

```text
backend/src/agents/
  graph.py
  state.py
  nodes/
    intake.py
    product_understanding.py
    sales_strategy.py
    page_planning.py
    copywriting.py
    visual_planning.py
    image_generation.py
    assembly.py
    qa.py

backend/src/services/
  prompt_registry.py
  generation_mode.py
  agent_run_service.py
  detail_page_assembly_service.py
```

Existing services should be reused where possible:

- `product_intake_service.py`
- `product_understanding_service.py`
- `sales_strategy_service.py`
- `visual_package_planner.py`
- `image_generation_service.py`
- `detail_page_package_service.py`
- `detail_page_orchestrator.py`
- `visual_page_renderer.py`
- `export_service.py`

The main change is orchestration. These services should become nodes in one generation pipeline.

## 12. Existing Sprint Repositioning

The previous Sprint 42-47 work is not wasted. It should be repositioned.

| Existing sprint | New role |
| --- | --- |
| Sprint 42 Flexible intake/product understanding | Start screen and Product Understanding Agent |
| Sprint 43 Sales strategy variants | Sales Strategy Agent and confirmation cards |
| Sprint 44 Visual package contract | Visual Planning Agent and provider-neutral image job contract |
| Sprint 44.5 AI image provider generation | Image Generation Agent with mock/real mode |
| Sprint 45 Detail page package editor | Review editor after generation |
| Sprint 46 Figma/marketplace alignment | Output package stage |
| Sprint 47 Orchestration/cost/QA | LangGraph-style generation pipeline, cost approval, QA gate |

The correction is not "delete the old work."  
The correction is "make the AI generation pipeline the product center."

## 13. New Implementation Sprint Plan

### Sprint 48: Agent Architecture And Prompt Contracts

Goal:

- define graph states
- define agent node contracts
- add prompt registry
- add mock/real mode switch
- add structured schemas for every agent output

User-visible result:

- none or minimal developer-visible run preview

### Sprint 49: AI Creation Start Flow

Goal:

- replace `/workspace` first experience with AI detail page intake
- support photo/URL/name/description input
- create project in `intake` state
- show generation progress shell

User-visible result:

- user starts from "AI 상세페이지 만들기" instead of editor-first workspace

### Sprint 50: Mock End-To-End Generation

Goal:

- run full pipeline in mock mode
- generate product understanding, sales strategy, page plan, copy, visual plan, placeholder images, and assembled page
- no API credits

User-visible result:

- one click creates a complete mock detail page draft

### Sprint 51: Real LLM Text Pipeline

Goal:

- connect real LLM for product understanding, sales strategy, page planning, and copywriting
- keep image generation mocked unless separately approved
- add provider/cost logs

User-visible result:

- real AI copy and page structure from product input

### Sprint 52: Real Image Pipeline

Goal:

- connect image generation/editing provider
- add explicit image cost approval
- add product identity QA
- let user choose generated images

User-visible result:

- AI-generated or AI-edited section images can be used in the detail page

### Sprint 53: Review Editor Reframe

Goal:

- make the existing editor open only after page assembly
- add AI command actions for copy/image/section changes
- show missing image and claim warnings clearly

User-visible result:

- generated detail page can be refined without feeling like a blank design tool

### Sprint 54: Export And Marketplace Package

Goal:

- export long PNG
- Figma export from generated page
- copy set export
- marketplace data package
- final QA checklist

User-visible result:

- seller can take the generated package to marketplace registration.

## 14. Success Criteria

The final product is successful when a solo seller can:

1. Open Sellform and immediately understand that it creates AI detail pages.
2. Provide a product photo, URL, product name, or short description.
3. See what AI understood about the product.
4. Confirm or adjust the recommended sales direction.
5. Generate a complete long mobile detail page draft.
6. See actual copy and image sections, not empty placeholders.
7. Generate or approve product visuals with explicit cost control.
8. Edit the generated page with simple AI commands.
9. Export PNG, Figma, copy set, and marketplace data.
10. Feel that the product went from "막막함" to "판매 가능한 상세페이지 초안."

## 15. Non-Goals

For this final generation architecture, do not prioritize:

- making Figma the first user experience
- building a full Photoshop-like editor
- requiring long manual forms before AI can start
- generating all images from scratch when original photos are better
- hiding cost usage from the user
- using real API calls during local mock testing

## 16. Key Product Decision

Sellform should become:

```text
AI detail page generation agent first,
review editor second,
export and marketplace assistant third.
```

This is the clearest path to the product the user originally wanted from the 19-image reference flow.
