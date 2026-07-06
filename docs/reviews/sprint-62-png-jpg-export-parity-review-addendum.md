# Sprint 62 Review Addendum: PNG/JPG Export Parity Recheck

> Review date: 2026-07-06
> Scope: frontend E2E failures found after the initial Sprint 62 review.

## Fixes applied

1. `frontend/e2e/completed-detail-page-export.spec.ts`
   - Added `/page/finalize` mock because the real download flow finalizes before creating an export job.
   - Validates `output_format` separately for PNG and JPG.
   - Returns format-specific download fixture values: `contentType`, filename, and blob body.

2. `frontend/e2e/upload-ready-detail-page.spec.ts`
   - Changed render route final-page mock from `/page/final` to `/page/final**` so it matches `/page/final?version_id=...`.
   - Verifies both `data-export-ready="error"` and the visible image-load failure message.

3. `frontend/src/components/DetailPageDocument.tsx`
   - Shows a visible export-mode warning when required images fail to load:
     `필수 이미지를 불러오지 못했습니다. 이미지를 확인한 뒤 다시 다운로드해 주세요.`
   - Keeps the existing worker contract through `data-export-ready` and `data-export-errors`.

## Recheck results

- Backend targeted tests: `10 passed`
- Frontend E2E: `3 passed`
- Frontend lint: passed with existing warnings only
- Frontend build: passed

## Final verdict

Sprint 62 now matches the PNG/JPG export parity plan for the covered contract:

- failed required images block export readiness;
- backend worker stops on render readiness errors;
- PNG and JPG export requests preserve their requested format;
- download UX handles both PNG and JPG paths;
- visible error UX exists for required image load failures.

Remaining risk: the backend Playwright worker is still mostly fake-tested. Run one real local/server canary before shipping to production.
