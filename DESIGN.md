# Design System - Sellform

## Product Context
- **What this is:** Sellform is an AI-assisted detail page creation service that turns product photos or product URLs into a sales-ready detail page draft.
- **Who it is for:** Solo sellers who know their product but do not know how to structure copy, visuals, sections, and marketplace-ready presentation.
- **Project type:** Commerce creation web app, not a technical AI dashboard.

## Design North Star
Sellform must not look like an AI technology product.

Sellform should feel like a bright, easy production service where a solo seller adds a product photo and receives a usable detail page draft.

The first impression should be:
- "I can make a selling page from my product photo."
- "This service understands what to say and what to show."
- "I do not need to know prompts, design tools, or marketing frameworks."

## Visual Tone
- **White-first:** Most screens should be white or near-white, with clean commerce surfaces.
- **Soft commerce:** The product, detail page preview, and selling flow should feel warmer than a SaaS dashboard.
- **Calm green accent:** Use green and mint as the main action and progress language.
- **Editorial product preview:** Show generated detail page drafts as the hero object, not abstract AI graphics.
- **Minimal AI decoration:** AI should appear through useful progress, analysis, and generated results, not flashy decoration.

## Avoid
- Dark dashboard frames on creation or review flows.
- Purple or blue AI gradients as the primary brand pattern.
- Excessive sparkle icons, magic language, and decorative AI effects.
- Generic SaaS hero layouts.
- Editor-first layouts where tools appear before the generated result.
- Dense admin sidebars on the first product creation experience.

## Color
- **Approach:** Light commerce palette with warm neutral surfaces and calm green action.
- **Primary green:** `#2FAE73` - primary CTA, selected states, completion.
- **Soft mint:** `#EAF8F1` - success backgrounds, progress cards, gentle panels.
- **Fresh surface:** `#F7FAF8` - page background and preview gutters.
- **White:** `#FFFFFF` - main canvas, forms, cards.
- **Ink:** `#111827` - primary text.
- **Muted text:** `#6B7280` - secondary copy.
- **Border:** `#E5EDE8` - card and input borders.
- **Blue secondary:** `#3D7CFF` - focus, links, and technical secondary actions only.
- **Warning:** `#F59E0B`
- **Error:** `#DC2626`

### Color Rules
- The start flow should read as at least 90% white or near-white.
- Green is the main action color. Blue is supportive, not the brand mood.
- Dark navy may be used for body text or small advanced panels, but not as a dominant page frame.
- Do not use purple-blue gradients for the primary CTA.

## Typography
- **Primary Korean UI font:** Pretendard.
- **Alternative Korean UI font:** SUIT.
- **Body:** Pretendard or SUIT, regular weight.
- **Headings:** Same family, stronger weight. Avoid trendy AI-startup display fonts.
- **Data and code:** JetBrains Mono or IBM Plex Mono only where tabular or code-like data is needed.

### Typography Rules
- Use clear commerce copy over technical AI language.
- Prefer "상세페이지 초안 만들기" over "AI 에이전트 실행".
- Prefer "판매 포인트 정리" over "프롬프트 생성".
- Avoid overdramatic hero copy and generic SaaS phrases.

## Layout
- **First screen:** Product intake first. Upload, URL, product name, and generation CTA should be the primary focus.
- **Generation screen:** Show progress as product understanding, selling strategy, visual plan, copy, and page assembly.
- **Result screen:** Show the generated detail page draft first, then editing controls.
- **Review editor:** Use a bright canvas-first editor with light side panels. Editing tools should support the preview, not dominate it.
- **Marketplace output:** Show export, registration, and validation as a final package after the draft is created.

### Layout Rules
- Do not start with a dark left sidebar.
- Do not start with an empty editor.
- Do not make the user choose sections before seeing an AI-made draft.
- The product image and generated detail page preview should be the visual anchor.

## Components
- **Upload box:** Large, friendly, white card with dashed border and green selected state.
- **URL input:** Same priority as upload, because sellers may start from an existing listing.
- **Primary CTA:** Solid green button with direct action text.
- **Progress tracker:** Simple horizontal or vertical steps with green completion and soft mint active state.
- **Generated copy cards:** Light cards for headline, subcopy, selling points, and section script.
- **Detail page preview:** Editorial long-form commerce preview, not a phone-only mockup by default.
- **Image slots:** Clearly show whether an image came from upload, URL extraction, mock generation, or real image generation.
- **QA warnings:** Plain language warnings for missing claims, unsafe copy, low image confidence, or marketplace issues.

## Motion
- **Approach:** Minimal-functional.
- Use small transitions for upload, generation progress, and result reveal.
- Avoid flashy AI loading animations.
- Avoid constant sparkles or glowing effects.

## UX Principles
- The user should not need to understand LLMs, agents, prompts, or image models.
- The service should explain what it is doing in seller language.
- The page should guide the user from product input to generated draft to editing to export.
- Every generated result should be editable.
- AI confidence and source information should be visible, but not intimidating.

## Screen Rules

### AI Creation Start
- White-first product creation page.
- Product photo or URL input is the main object.
- Template/style selection is optional and secondary.
- CTA should say something like "상세페이지 초안 만들기".

### Generation Progress
- Show understandable steps:
  1. 상품 이해
  2. 판매 포인트 정리
  3. 상세페이지 문구 작성
  4. 이미지 연출 계획
  5. 상세페이지 초안 조립
- Avoid raw agent names as the main UI.

### Generated Result
- Show the full detail page draft first.
- Provide generated script/copy next to the visual preview.
- Show which images are real, extracted, mocked, or generated.

### Review Editor
- Light canvas.
- Light editing panels.
- Keep advanced controls available but visually quiet.
- Editing should feel like improving a generated sales page, not operating a technical design tool.

## Copy Voice
- Clear, practical, seller-friendly Korean.
- Explain benefits in everyday commerce language.
- Avoid "마법", "프롬프트", "워크플로우", "에이전트 실행" as customer-facing primary copy.
- Use AI terminology only in settings, logs, diagnostics, or developer-facing screens.

## QA Checklist
- Does the first screen look like a detail page creation service, not an AI dashboard?
- Is the product input the first thing the user understands?
- Is the primary action green or mint-based, not purple-blue gradient?
- Is there no dark dashboard frame around the creation flow?
- Does the generated result appear before detailed editing controls?
- Can a solo seller understand the next step without knowing AI terminology?
- Are product images and generated images clearly labeled by source?
- Does the review editor still feel bright and commerce-focused?

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-07-03 | Adopt white-first soft commerce direction | Sellform should feel like an easy detail page production service for solo sellers, not an AI technology dashboard. |
| 2026-07-03 | Use calm green as the main accent | Green supports commerce, progress, and trust better than purple-blue AI gradients for this product. |
| 2026-07-03 | Make generated detail page preview the primary object | The user is buying a sales-ready page draft, not an editor or agent console. |
