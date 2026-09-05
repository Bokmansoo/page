# Sellform V2 Sprint UX-1 code review

## Result

The normal seller journey now runs as one flow: product photos and product information → automatic generation progress → generated detail page. The planning/storyboard screen is no longer the mandatory next step.

## Implemented

- The main intake submits `ux_auto_generate: true` and keeps the uploaded image order in the persisted agent run.
- After upload, the seller is routed to `/workspace?runId=...`, where the existing persisted generation run starts and reports progress.
- The normal intake no longer forces the structured-input review or planning-mode picker. The structured review remains available through the explicit `/workspace?advanced=1` route.
- Automatic runs bypass only the *intermediate UI gates* for asset understanding and fact evidence. They still store the uploaded assets, seller input, fact snapshot, agent output, and page version under the current workspace.
- The generation request now sends the authenticated browser session cookie. This fixes the previous run request that could lose authentication after the intake screen.
- The existing result page continues to expose review editing and advanced editing, so storyboard and section-level changes remain available after generation rather than blocking the first result.

## Image behavior

- Uploaded product photos are retained as the product-grounding references used by the image-generation stage and page assembly.
- The active image provider determines whether lifestyle variations (for example, in-use or charging scenes) are generated as new assets. Without a configured image provider, the safe fallback uses the uploaded product images and HTML/CSS composition; it does not pretend that a new AI image was made.
- Supplier/reference images remain reference-only unless their usage status permits final output.

## Verification

- `npm.cmd run lint` — passed; existing repository warnings only.
- `backend/.venv/Scripts/python.exe -m pytest tests/test_agent_run_api.py tests/test_mock_agent_generation.py -q -p no:cacheprovider` — 11 passed.
- `git diff --check` — passed (line-ending notices only).

## Follow-up operational check

To see newly generated in-use/charging scene assets in production, configure a supported image provider and its credentials, then create a project with one clear front product image plus additional detail images. The automatic route will otherwise finish with the safe source-image fallback.
