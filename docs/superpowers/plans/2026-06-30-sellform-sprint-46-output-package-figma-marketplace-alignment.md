# Sellform Sprint 46 Output Package, Figma, And Marketplace Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the generated detail page into a full sales package: PNG, editable web page, Figma export, and marketplace registration data.

**Architecture:** Reframe Figma and marketplace functionality as output actions after detail page generation. Preserve existing export, Figma plugin, and marketplace package work while changing their entry point and copy.

**Tech Stack:** FastAPI, existing export services, Figma plugin package service, marketplace package services, Next.js.

---

## File Structure

- Modify: `backend/src/services/export_service.py`.
- Modify: `backend/src/services/figma_plugin_package_service.py`.
- Modify: `backend/src/api/figma_plugin.py`.
- Modify: `backend/src/api/marketplaces.py` if present.
- Create: `backend/src/services/sales_package_service.py`.
- Create: `backend/tests/test_sales_package_service.py`.
- Create: `frontend/src/components/SalesPackageExportPanel.tsx`.
- Modify existing Figma export dialog copy to clarify it is an advanced editing/export path.

## Tasks

### Task 1: Sales Package Service

- [ ] Define package outputs: `long_png`, `editable_web_page`, `figma_payload`, `marketplace_package`, `copy_sheet`, and `visual_assets`.
- [ ] Add tests that a completed detail page package can produce output metadata.

### Task 2: PNG Export As Primary Output

- [ ] Keep long mobile PNG as the first visible export.
- [ ] Ensure selected sales direction and visual plan reach the renderer.
- [ ] Add regression tests for style/direction propagation.

### Task 3: Figma Repositioning

- [ ] Rename UI copy from "main import path" to "Figma에서 고급 편집".
- [ ] Keep manifest/plugin docs, but move them out of the core first-run flow.
- [ ] Ensure Figma plugin imports the actual visual detail page package, not generic placeholder blocks.

### Task 4: Marketplace Package Alignment

- [ ] Feed marketplace package generation from the final sales package.
- [ ] Include title, tags, category, representative image, detail page artifact, price, delivery, returns, and SEO metadata.
- [ ] Keep external marketplace submission behind explicit user approval.

### Task 5: Output Panel UI

- [ ] Add buttons: `PNG 저장`, `웹에서 수정`, `Figma로 편집`, `마켓 등록 준비`.
- [ ] Show "등록 데이터 준비됨" only after required marketplace fields pass validation.

### Task 6: Verification

- [ ] Run export, Figma plugin package, and marketplace package tests.
- [ ] Manually verify output actions appear after detail page generation, not before.

## Done Criteria

- Sellform outputs a complete sales package.
- Figma and marketplace features are preserved but correctly positioned.
- The first product success moment remains the generated detail page package.

