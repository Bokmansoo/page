# Sellform Final Product Design: AI Detail Page MD

> Status: Approved direction from product interview on 2026-06-30
> Scope: Final product vision plus implementable requirements
> Core line: 사진/URL만 넣으면, 팔릴 이유부터 상세페이지까지

## 1. Product Definition

Sellform is an AI detail page MD for solo sellers. A seller can provide any available product input, such as product photos, a product URL, a short description, reference images, or competitor links. Sellform analyzes the product, explains how to sell it, generates copy and image direction, assembles a full mobile commerce detail page, and prepares a marketplace-ready product package.

The product is not primarily a Figma exporter, template picker, or marketplace uploader. Those are downstream capabilities. The main product promise is:

**Sellform turns a seller's product material into a sales-ready package.**

## 2. Target User

The primary user is a solo seller who has a product but does not know how to present it.

Typical user thoughts:

- "I have a product, but I do not know how to structure the detail page."
- "I do not know what headline or sales copy will make people interested."
- "My photos are ordinary. I do not know what background or scene would make them look sellable."
- "I do not know whether to emphasize price, design, safety, function, gift value, or trust."
- "I want to upload to Smartstore or another marketplace, but the whole process feels blocked."

Secondary users include sourcing sellers, small agencies, and brand operators. They matter later, but the final product should still feel simple enough for a solo seller.

## 3. Core Value

The strongest paid value is not only saving design cost or time. The deepest value is:

**막막함 해결 + 판매 가능한 상태까지 완성.**

The user should feel:

**"이제 올릴 수 있겠다."**

## 4. Brand And Positioning

Keep the brand name **Sellform**.

Use professional naming with friendly product language.

- Brand: Sellform
- Descriptor: 1인 셀러를 위한 AI 상세페이지 MD
- Main message: 사진/URL만 넣으면, 팔릴 이유부터 상세페이지까지
- Supporting copy: AI가 상품을 분석해 판매 전략, 문구, 이미지 연출, 상세페이지, 마켓 등록 정보를 한 번에 만들어줍니다.

The tone should be friendly but expert. The service should not feel like a heavy design tool, and it should not feel like a toy.

## 5. Final User Flow

```text
Start
  -> Provide product input
  -> AI understands product
  -> Fast confirmation card
  -> AI recommends one sales direction plus two alternatives
  -> AI plans required visual roles and prompts
  -> Seller approves paid image generation
  -> Image model creates or edits product visuals
  -> Seller reviews generated visuals
  -> Generate full detail page package
  -> Edit with AI commands
  -> Export PNG / web editor / Figma / marketplace data
```

## 6. Product Input

The final product should accept flexible input.

The first screen should ask:

**상품 사진, URL, 설명 중 아무거나 넣어주세요.**

Supported input types:

- Product photos
- Product URL
- Direct product description
- Competitor or reference product links
- Reference images

The user should not need to fill a long form before starting. AI should begin with what is available and ask only for missing high-impact information.

## 7. AI Product Understanding

After input, AI should produce a short understanding card:

- Product type
- Target customer
- Core buyer problem
- Main selling angle candidates
- Important facts
- Risky or unverified assumptions
- Suggested representative images

Example:

```text
AI가 이렇게 이해했어요. 맞나요?

상품 유형: 유아용 밸런스 바이크
타깃: 2~5세 아이를 둔 부모
핵심 고민: 첫 자전거가 안전할까?
메인 소구 후보: 안전한 첫 라이딩 / 감성 디자인 / 성장 단계 활용
추천 톤: 따뜻하고 신뢰감 있는 육아용품 톤
대표 이미지: 1번 사진
```

Each row should offer:

- Use as-is
- See other suggestions
- Edit directly

## 8. Fast Confirmation

Before generating the full page, Sellform should quickly confirm:

- Target customer
- Main selling point
- Product tone/style
- Price or discount information
- Selected images

This confirmation must feel like a 30-second check, not a form.

Primary button:

**맞아요, 생성하기**

Secondary action:

**조금 수정하기**

## 9. Sales Direction Variants

Sellform should generate:

- One recommended direction
- Two alternative directions

Internally, the variants can map to persuasion, emotional, and information-heavy structures. Externally, the UI should present the AI recommendation first so the user does not need to decide from a blank state.

Example:

- AI recommendation: 안전 설득형
- Alternative 1: 감성 육아형
- Alternative 2: 기능 정보형

Each direction card should include:

- Representative headline
- Target customer
- Main selling angle
- Detail page flow
- Recommended image/background feeling
- Why AI recommends it

## 10. Detail Page Structure

The default final detail page should follow a persuasive sales order:

1. Problem statement: customer pain or hesitation
2. Main selling point: how this product solves the core problem
3. Supporting point B: additional benefit
4. Supporting point A reinforcement: proof, image, comparison, or usage scene
5. Supporting points B-D: remaining benefits
6. One-sentence summary: the overall sales message
7. Product information: final purchase-decision information

This structure should be adapted by category. A kids product, electronic accessory, food item, fashion item, and home product should not all sound or look the same.

## 11. AI Copy Requirements

Sellform should generate copy for:

- Detail page title
- Hero headline
- Hero subcopy
- Problem statement
- Main selling point
- Benefit headlines
- Benefit body copy
- Proof and comparison copy
- Usage scene captions
- FAQ
- Product information
- CTA
- Smartstore title
- Search tags
- SEO title and description

Copy should be tied to verified or user-approved facts where factual claims are made. Unverified claims should be marked for review or avoided.

## 12. Image And Visual Generation Requirements

The final product should support the whole visual package:

- Representative product cut
- Background-removed product cut
- Lifestyle usage scene
- Problem statement scene
- Benefit-specific image
- Detail close-up crop
- Comparison table
- Before/after style visual
- Icon and badge set
- FAQ or information graphic
- Smartstore thumbnail
- Mid-page CTA image

This does not mean every image must be fully generated from scratch. Sellform should combine:

- Original product photos
- Cropped or enhanced product photos
- Background replacement
- Lifestyle composition
- Generated supporting visuals
- Icons, badges, and comparison graphics

The AI visual pipeline has separate responsibilities:

1. A vision-capable model understands the uploaded product photos.
2. A text model turns the confirmed sales strategy into visual roles and prompts.
3. An image model generates or edits the required visual assets.
4. A quality gate checks output validity and product-identity preservation.
5. The seller approves generated outputs before the page assembler can use them.

Provider strategy:

- Keep the visual-job contract provider-neutral.
- Use OpenAI GPT Image through a provider adapter as the first implementation.
- Use reference-image editing for any scene containing the real product.
- Use text-only generation only for backgrounds and supporting visuals that do not need to reproduce the product.
- Keep marketing copy, prices, claims, logos, and certification marks as editable page layers instead of generating them inside images.
- Require explicit cost approval before any paid image request.
- Continue with original photos and marked visual needs when image generation is unavailable.

Important principle:

**The actual product should remain believable and recognizable.**

## 13. Final Output Package

The final product output is a package, not a single file.

Package contents:

- Long mobile detail page PNG
- Web-based editable detail page
- Figma-editable export for advanced editing
- AI sales strategy document
- Copy set
- Image generation and editing history
- Marketplace registration data
- Smartstore/Coupang-ready draft data where connected

## 14. Editing UX

The editor should not feel like Photoshop or Figma for solo sellers. It should feel like instructing an AI MD.

Preferred editor structure:

- Left: AI sales strategy and section outline
- Center: mobile detail page preview
- Right: command and edit panel

Core edit actions:

- Make this headline stronger
- Make it more natural
- Make it more emotional
- Reduce exaggeration
- Create another background
- Change the image scene
- Move this section earlier
- Remove this section
- Add more proof
- Make it Smartstore-friendly

The user should be able to edit text directly, but the primary interaction should be AI-assisted command editing.

## 15. Marketplace Package

Marketplace integration is a downstream output, not the main product start point.

Sellform should prepare:

- Product title
- Category suggestion
- Search tags
- Representative image
- Detail page image
- Price and discount fields
- Delivery and return information
- Required notices
- SEO title and meta description

Actual submission to Smartstore, Coupang, or other marketplaces should remain approval-gated.

## 16. Existing Implementation Repositioning

The existing implementation is not wasted. It should be repositioned.

| Existing area | New role |
| --- | --- |
| Product facts and source extraction | Product understanding foundation |
| Style candidate selection | Sales direction and tone recommendation foundation |
| Visual background candidates | Early image direction system |
| Page section generator | First-generation detail page assembly engine |
| Image asset mapping | Existing photo placement and visual slot assignment |
| Commerce visual cut renderer | Long detail page preview and PNG output foundation |
| Figma plugin/export | Advanced editing/export path after the detail page exists |
| Marketplace package and registration | Final sales package output path |

The current issue is not that these features are useless. The issue is that the product currently shows too much downstream machinery before the user experiences the main magic: AI selling strategy, copy, image direction, and a complete detail page.

## 17. What Changes

The product center moves from:

```text
facts -> style -> page -> figma/export -> marketplace
```

to:

```text
input -> AI sales strategy -> quick confirmation -> recommended sales direction -> image/copy/detail page package -> edit/export/register
```

Figma and marketplace functions become final-stage outputs.

## 18. UI Experience Direction

Sellform should default to a light, white workspace. The product is for solo sellers who feel blocked, so the interface should feel clear, calm, and work-ready rather than dark, technical, or tool-heavy.

Primary UI principles:

- Use a white or near-white page background.
- Use white cards with subtle borders for input, AI understanding, strategy, and preview panels.
- Use dark neutral text for readability and muted gray for helper text.
- Use Sellform green for primary progress, approval, and completion states.
- Use violet or blue sparingly for AI recommendation accents, not as the dominant theme.
- Avoid making the first screen feel like Figma, Photoshop, or a developer console.
- Show the core promise immediately: photo, URL, or text input can become sales strategy, copy, visuals, and a detail page.

Recommended final workspace layout:

- Top: light navigation with Sellform brand, current project state, export/register actions.
- Start screen: centered intake surface with the message "사진/URL만 넣으면, 팔릴 이유부터 상세페이지까지."
- Generation screen: left AI strategy and outline, center mobile detail page preview, right AI command and edit panel.
- Output screen: package checklist for PNG, editable page, Figma export, copy set, and marketplace data.

This light UI direction should begin in Sprint 42 so the first user-visible moment already matches the final product identity.

## 19. Implementation Sprint Breakdown

The final product should be implemented through these sprint tracks:

- Sprint 42: Flexible product intake and AI product understanding
- Sprint 43: AI sales strategy, confirmation card, and direction variants
- Sprint 44: Visual package planning and image generation/editing contract
- Sprint 44.5: Real AI image provider integration, product-preserving generation, review, and approval
- Sprint 45: Detail page package generator and AI-assisted editor shell
- Sprint 46: Output package, Figma repositioning, and marketplace package alignment
- Sprint 47: End-to-end generation orchestration, cost controls, and QA

Each sprint should produce a testable user-visible slice.

## 20. Completion Criteria

The final experience is successful when a solo seller can:

1. Add a photo, URL, description, or any combination.
2. See how Sellform understood the product.
3. Quickly confirm or adjust the selling direction.
4. Generate one recommended full detail page plus alternatives.
5. See actual copy and visual sections, not empty placeholders.
6. Generate or edit product visuals with explicit cost approval and review them before use.
7. Request image, copy, section, and style changes through AI commands.
8. Export a long PNG.
9. Open/edit the result in Figma when needed.
10. Prepare marketplace registration data.
11. Feel that the product went from "막막함" to "올릴 수 있음."
