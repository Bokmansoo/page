# Sellform Sprint 45 Detail Page Package And AI Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a full editable detail page package from the confirmed sales strategy, copy, and visual package, then expose an AI-assisted editor shell.

**Architecture:** Keep `ProductPage` and `PageSection`, but enrich page generation with sales-strategy and visual-package inputs. The editor should be three-pane: strategy outline, mobile preview, command/edit panel.

**Prerequisite:** Consume the Sprint 44 visual plan and Sprint 44.5 approved generated assets. Unapproved, rejected, or failed AI outputs must never be inserted automatically; retain the existing-photo and explicit `image needed` fallback paths.

**Tech Stack:** FastAPI, SQLAlchemy, existing page generator, visual page renderer, Next.js, TypeScript.

---

## File Structure

- Modify: `backend/src/services/page_generator.py`.
- Create: `backend/src/services/detail_page_package_service.py`.
- Modify: `backend/src/services/visual_page_renderer.py`.
- Create: `backend/tests/test_detail_page_package_service.py`.
- Modify: `backend/tests/test_page_generator_visual_copy.py`.
- Create: `frontend/src/components/DetailPagePackageEditor.tsx`.
- Create: `frontend/src/components/AiEditCommandPanel.tsx`.

## Tasks

### Task 1: Detail Page Package Contract

- [ ] Define package fields: `sales_strategy`, `copy_sections`, `visual_plan`, `page_sections`, `marketplace_copy`, and `export_targets`.
- [ ] Add tests that the package contains both strategy and renderable page sections.

### Task 2: Sales-Driven Page Generation

- [ ] Update page generation to start from confirmed sales strategy.
- [ ] Resolve each visual role from an original asset or a Sprint 44.5 `approved` generated asset before rendering.
- [ ] Ensure default section order follows: problem, main selling point, supporting point, proof, remaining benefits, summary, product information.
- [ ] Add category-specific variants without creating a new template system.

### Task 3: Visual Slot Integration

- [ ] Attach visual roles and selected/generated asset references to sections.
- [ ] Render existing product photos where available.
- [ ] Render explicit "image needed" states only when visual plan lacks a source.
- [ ] Never render an unapproved generated asset into the detail page preview, PNG, Figma payload, or marketplace package.

### Task 4: Three-Pane Editor Shell

- [ ] Left pane: sales strategy and section outline.
- [ ] Center pane: mobile detail page preview.
- [ ] Right pane: AI edit commands and direct edit controls.
- [ ] Add command buttons: stronger headline, natural tone, emotional tone, reduce exaggeration, change background, move section, remove section.

### Task 5: Section-Level AI Edit Contract

- [ ] Define edit command payload: `section_id`, `command_type`, `freeform_instruction`, and `scope`.
- [ ] Implement deterministic mock edits first, such as appending a revision marker or selecting an alternate copy candidate.
- [ ] Add tests for section-level edit commands.

### Task 6: Verification

- [ ] Run page package tests.
- [ ] Run existing export/visual renderer tests.
- [ ] Manually verify the editor shows strategy, preview, and edit controls in one workflow.

## Done Criteria

- The user sees a full detail page package, not a Figma placeholder.
- Every rendered visual is either an original asset or a seller-approved Sprint 44.5 asset.
- The editor supports AI-command-style editing.
- Existing renderer work is upgraded into the main preview path.
