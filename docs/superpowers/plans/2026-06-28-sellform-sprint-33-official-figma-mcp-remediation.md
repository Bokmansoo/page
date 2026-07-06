# Sprint 33 Official Figma MCP Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Sprint 33 mock Figma bridge with an honest, contract-aligned Remote MCP export flow using `use_figma`, `upload_assets`, OAuth state, real node IDs, and complete regression coverage.

**Architecture:** FastAPI owns tenant authorization, canonical payload generation, job state, and polling. A localhost-only TypeScript bridge owns Streamable HTTP MCP connectivity, OAuth continuation, `use_figma` layout creation, and `upload_assets` image placement. Figma failure remains isolated from Sellform editing and PNG export.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, Next.js 14, TypeScript, `@modelcontextprotocol/sdk` 1.29.x, Figma Remote MCP, pytest, Jest, Playwright.

---

## File map

- `backend/src/services/figma_design_payload_builder.py`: canonical payload producer.
- `backend/src/services/figma_export_job_service.py`: job idempotency and retry rules.
- `backend/src/services/figma_bridge_client.py`: bridge HTTP/error contract.
- `backend/src/services/figma_mcp_adapter.py`: legacy payload-only fallback.
- `backend/src/api/pages.py`: live-export, status, retry APIs and status transitions.
- `backend/src/db/models.py`: `FigmaExportJob` persistence.
- `integrations/figma-bridge/src/oauth-store.ts`: OAuth state, verifier, tokens, and authorization continuation.
- `integrations/figma-bridge/src/figma-mcp-client.ts`: Streamable HTTP MCP client and tool calls.
- `integrations/figma-bridge/src/figma-renderer.ts`: canonical payload validation and `use_figma` JavaScript generation.
- `integrations/figma-bridge/src/server.ts`: protected local bridge endpoints.
- `frontend/src/components/figma/FigmaExportDialog.tsx`: export controls and timeout.
- `frontend/src/components/figma/FigmaExportStatus.tsx`: progress/error presentation.
- `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`: component integration only.

### Task 1: Lock the canonical payload contract

**Files:**
- Modify: `backend/tests/test_figma_design_payload_builder.py`
- Create: `integrations/figma-bridge/src/types.ts`
- Modify: `integrations/figma-bridge/tests/figma-renderer.test.ts`
- Modify: `integrations/figma-bridge/src/figma-renderer.ts`

- [ ] **Step 1: Add backend schema-version assertions**

```python
assert payload["schema_version"] == "1.0"
assert payload["page"]["canvas_width"] == 860
assert payload["cuts"][0]["section_type"] == "header"
assert "supporting_text" in payload["cuts"][0]
```

- [ ] **Step 2: Add a bridge test using the exact backend payload**

```ts
expect(command.rootName).toBe('Sellform / Test product');
expect(command.canvasWidth).toBe(860);
expect(command.cuts[0].sectionType).toBe('header');
expect(command.cuts[0].supportingText).toBe('Evidence');
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```cmd
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_figma_design_payload_builder.py -q
cd integrations\figma-bridge
npm.cmd test -- --runInBand
```

Expected: schema version and canonical bridge contract assertions fail.

- [ ] **Step 4: Add `schema_version` and replace the bridge-only payload shape**

Create `types.ts` with `CanonicalFigmaPayload`, `CanonicalFigmaCut`, and `CompiledFigmaLayout`. Make the renderer consume `section_type`, `supporting_text`, `brand.primary_color`, `brand.font_family`, and `page.canvas_width`.

- [ ] **Step 5: Run both tests and verify GREEN**

Expected: canonical contract tests pass.

### Task 2: Replace legacy SSE and fake OAuth

**Files:**
- Modify: `integrations/figma-bridge/package.json`
- Modify: `integrations/figma-bridge/src/config.ts`
- Modify: `integrations/figma-bridge/src/oauth-store.ts`
- Modify: `integrations/figma-bridge/src/figma-mcp-client.ts`
- Modify: `integrations/figma-bridge/tests/server.test.ts`
- Create: `integrations/figma-bridge/tests/figma-mcp-client.test.ts`

- [ ] **Step 1: Add failing transport/tool tests**

```ts
expect(client.requiredTools()).toEqual(['use_figma']);
expect(client.optionalTools()).toContain('upload_assets');
expect(client.transportKind()).toBe('streamable-http');
```

Add a callback test proving that an unknown or missing OAuth `state` is rejected and that no token beginning with `figma_access_token_` is stored.

- [ ] **Step 2: Run Jest and verify RED**

Expected: tests fail because the client still uses `SSEClientTransport`, fake OAuth, and `write-to-canvas`.

- [ ] **Step 3: Upgrade the stable v1 SDK**

```cmd
cd integrations\figma-bridge
npm.cmd install @modelcontextprotocol/sdk@1.29.0
```

- [ ] **Step 4: Implement Streamable HTTP and OAuth continuation**

Use:

```ts
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
```

The OAuth store persists tokens, client information, PKCE verifier, state, and pending authorization URL. Authentication-required results return only the SDK-produced authorization URL. The callback validates state and calls `finishAuth(code)`; it never constructs a mock token.

- [ ] **Step 5: Discover official tools**

Require `use_figma`; treat `upload_assets` as required only when the payload contains images. Return `MCP_TOOL_UNSUPPORTED` or `IMAGE_UPLOAD_UNSUPPORTED` before rendering when unavailable.

- [ ] **Step 6: Run Jest and TypeScript build**

Expected: all bridge tests and `npm.cmd run build` pass.

### Task 3: Generate real Figma commands and reject false success

**Files:**
- Modify: `integrations/figma-bridge/src/figma-renderer.ts`
- Modify: `integrations/figma-bridge/src/figma-mcp-client.ts`
- Modify: `integrations/figma-bridge/src/server.ts`
- Modify: `integrations/figma-bridge/tests/figma-renderer.test.ts`
- Modify: `integrations/figma-bridge/tests/server.test.ts`

- [ ] **Step 1: Add failing response and image tests**

```ts
expect(() => parseCreatedNodeId({ content: [] })).toThrow('INVALID_MCP_RESPONSE');
expect(uploadCalls[0].name).toBe('upload_assets');
expect(uploadCalls[0].arguments.nodeUrl).toContain('node-id=');
```

- [ ] **Step 2: Verify RED**

Expected: the current `0-1` fallback makes the response test fail and images are represented as URL-valued `imageRef`.

- [ ] **Step 3: Generate incremental `use_figma` JavaScript**

The renderer returns:

- root-frame creation code;
- one cut-frame creation command at a time;
- image-slot node names that can be resolved to actual node IDs;
- text creation using editable TextNodes and Auto Layout.

No external URL is assigned to `imageRef`.

- [ ] **Step 4: Upload images after node creation**

Call `upload_assets` with each public HTTPS image URL and the actual target node URL. Parse and validate the real root node ID from MCP structured/text content.

- [ ] **Step 5: Remove false success**

Missing root node ID returns:

```json
{
  "error_code": "INVALID_MCP_RESPONSE",
  "error_message": "Figma did not return a created node id."
}
```

- [ ] **Step 6: Verify bridge tests and build**

Expected: tests pass with no mock node fallback.

### Task 4: Correct backend state, auth URL, retry, and idempotency

**Files:**
- Modify: `backend/src/db/models.py`
- Modify: `backend/src/services/figma_export_job_service.py`
- Modify: `backend/src/services/figma_bridge_client.py`
- Modify: `backend/src/services/figma_mcp_adapter.py`
- Modify: `backend/src/api/pages.py`
- Modify: `backend/tests/test_figma_export_job_service.py`
- Modify: `backend/tests/test_figma_live_export_api.py`
- Modify: `backend/tests/test_figma_mcp_adapter.py`

- [ ] **Step 1: Add failing backend tests**

Test that:

```python
assert observed_statuses == ["authenticating", "rendering", "completed"]
assert status_response["auth_url"] == "https://mcp-auth.example/authorize"
assert retry_completed.status_code == 409
assert adapter_result["status"] == "not_configured"
```

- [ ] **Step 2: Run targeted tests and verify RED**

Expected: auth URL and rendering transition are absent, completed retry is accepted, and the adapter regression fails.

- [ ] **Step 3: Persist safe job metadata**

Add nullable `auth_url`, enforce the logical idempotency key, and clear stale result/error/auth fields when retrying a failed job.

- [ ] **Step 4: Implement real transitions**

Set `authenticating` before connection, `rendering` when the bridge begins canvas work, and `completed` only after validated URLs arrive. Preserve `AUTH_REQUIRED` and `auth_url` in failed status.

- [ ] **Step 5: Restrict retry**

Return HTTP 409 unless the current job status is `failed`. Reusing completed identical payload returns the existing completed job without another background task.

- [ ] **Step 6: Restore adapter fallback contract**

When live bridge delivery is unavailable, return:

```python
{"success": False, "status": "not_configured", "payload": payload}
```

- [ ] **Step 7: Run targeted tests and verify GREEN**

Expected: all Figma backend tests pass.

### Task 5: Split and harden the frontend workflow

**Files:**
- Create: `frontend/src/components/figma/FigmaExportDialog.tsx`
- Create: `frontend/src/components/figma/FigmaExportStatus.tsx`
- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
- Modify: `frontend/e2e/sprint33-live-figma-export.spec.ts`
- Modify: `frontend/e2e/sprint32-figma-export.spec.ts`

- [ ] **Step 1: Add failing E2E cases**

Add cases proving:

- invalid non-design URL does not call the API;
- `auth_url` comes from the API;
- polling stops after the configured test timeout;
- PNG alternative remains reachable;
- Sprint 32 payload-only export still sends its request.

- [ ] **Step 2: Run Playwright and verify RED**

Expected: invalid URL, timeout, or Sprint 32 regression cases fail.

- [ ] **Step 3: Extract focused components**

Use the shared backend URL and tenant-header helpers. Remove all hard-coded `localhost:8000`, mock IDs, `dummy_client_id`, and port `3011` values from the Figma components.

- [ ] **Step 4: Implement validation and bounded polling**

Accept only HTTPS `figma.com/design/` URLs. Poll around once per second, stop after two minutes, and show an actionable timeout state.

- [ ] **Step 5: Run E2E and build**

Expected: Sprint 32 and 33 E2E pass; Next.js production build succeeds.

### Task 6: Secure the local bridge and documentation

**Files:**
- Modify: `.gitignore`
- Modify: `.env.example`
- Modify: `integrations/figma-bridge/src/config.ts`
- Modify: `integrations/figma-bridge/src/server.ts`
- Modify: `docs/runbooks/2026-06-27-sellform-figma-mcp-runbook.md`
- Modify: `docs/troubleshooting/2026-06-27-sellform-sprint-33-live-figma-export.md`

- [ ] **Step 1: Add security assertions**

Bridge tests assert that an empty bridge token causes export requests to fail closed and that the server binds to `127.0.0.1`.

- [ ] **Step 2: Verify RED**

Expected: current optional token middleware and all-interface listener fail.

- [ ] **Step 3: Apply security defaults**

Add:

```gitignore
.sellform/
node_modules/
integrations/figma-bridge/dist/
```

Require a bridge token, remove unrestricted CORS, and bind to `127.0.0.1`.

- [ ] **Step 4: Update operational docs**

Document OAuth prerequisites, Full seat/edit permission, public image URL requirements, startup sequence, manual QA, and the distinction between automated mock tests and live Figma evidence.

### Task 7: Full verification and review evidence

**Files:**
- Modify: `docs/testing/2026-06-27-sellform-sprint-33-live-figma-export-test-log.md`
- Modify: `docs/reviews/2026-06-27-sellform-sprint-33-code-review.md`

- [ ] **Step 1: Run the complete verification set**

```cmd
backend\.venv\Scripts\python.exe -B -m pytest backend\tests -q --basetemp=.pytest-tmp-sprint33-remediation

cd integrations\figma-bridge
npm.cmd test -- --runInBand
npm.cmd run build

cd ..\..\frontend
npm.cmd run build
npm.cmd run test:e2e -- sprint32-figma-export.spec.ts sprint33-live-figma-export.spec.ts --output=test-results-sprint33-remediation
```

- [ ] **Step 2: Record exact outputs**

The test log records commands, counts, failures, warnings, and whether live Figma QA was performed.

- [ ] **Step 3: Update the review conclusion**

Use:

- `Approved` only after automated verification and real Figma QA;
- `Conditionally approved` when automated verification passes but real-account QA is pending;
- `Changes requested` if any required automated verification fails.

- [ ] **Step 4: Confirm no secrets or generated dependencies are tracked**

```cmd
git status --short
git check-ignore .sellform integrations/figma-bridge/node_modules integrations/figma-bridge/dist
```

Expected: all three paths are ignored and no OAuth/token material is listed.
