# LG-14 Detail Page Beta real-service verification

This runbook is the acceptance authority for the six local Golden Paths. It
drives the existing browser, FastAPI, LangGraph, PostgreSQL, worker, Quality
Bar, promotion, and export path. It does not use route/API mocks or assemble a
passing state with direct database writes.

## Prerequisites and safety

- Repository: `C:\page`
- Frontend: `http://127.0.0.1:3001`
- Backend: `http://127.0.0.1:8001`
- PostgreSQL: `127.0.0.1:5433/sellform_test`
- Docker container: `sellform-postgres-test`
- Browser: visible/headed Chromium
- Provider mode: deterministic `mock`; keep all provider API keys empty
- Auth: `SELLFORM_AUTH_MODE=development`. The first API request creates the
  local development session; no external login is required.
- Data: local generated content only. Never point these commands at Supabase,
  a customer database, or a commercial product URL.

Start and migrate the existing PostgreSQL test stack from `C:\page\backend`:

```powershell
.\scripts\start_postgres_lg12_e2e.ps1 -Mode migrate
docker inspect --format '{{.State.Health.Status}}' sellform-postgres-test
docker exec sellform-postgres-test psql -U sellform_test -d sellform_test -c "SELECT 1"
```

The health result must be `healthy`; the SQL command must return `1`.

## Safe owned-URL fixture

In a separate PowerShell window, launch the tracked, generic local page:

```powershell
python -m http.server 4177 --bind 127.0.0.1 --directory C:\page\frontend\e2e\fixtures
```

Verify `http://localhost:4177/lg14-owned-product.html` in the browser. The
fixture has no brand, customer data, query token, or external asset.

## Backend

In a new PowerShell window:

```powershell
cd C:\page\backend
$testUrl = "postgresql+psycopg://sellform_test:test-only-password@127.0.0.1:5433/sellform_test"
$env:APP_ENV = "test"
$env:SELLFORM_ALLOW_TEST_DATABASE = "1"
$env:TEST_DATABASE_URL = $testUrl
$env:E2E_DATABASE_URL = $testUrl
$env:DATABASE_URL = $testUrl
$env:SELLFORM_LANGGRAPH_CHECKPOINT_DATABASE_URL = $testUrl
$env:SELLFORM_GRAPH_RUNTIME = "langgraph"
$env:SELLFORM_AUTH_MODE = "development"
$env:SELLFORM_GENERATION_MODE = "mock"
$env:SELLFORM_IMAGE_GENERATION_MODE = "mock"
$env:SELLFORM_IMAGE_WORKER_ENABLED = "true"
$env:SELLFORM_ALLOW_LOCAL_URL_FIXTURE = "true"
$env:SELLFORM_WEB_BROWSING_ENABLED = "false"
$env:SELLFORM_OCR_AI_TRANSLATION_ENABLED = "false"
$env:SELLFORM_ASSET_AI_VISION_ENABLED = "false"
$env:SELLFORM_RAG_RUNTIME_MOCK = "true"
$env:SELLFORM_EXPORT_RENDER_BASE_URL = "http://127.0.0.1:3001"
$env:SELLFORM_PUBLIC_APP_URL = "http://127.0.0.1:3001"
$env:ANTHROPIC_API_KEY = ""
$env:OPENAI_API_KEY = ""
$env:GOOGLE_API_KEY = ""
.\.venv\Scripts\python.exe -m uvicorn src.app:app --host 127.0.0.1 --port 8001
```

Confirm `http://127.0.0.1:8001/` returns HTTP 200.

## Frontend

In another PowerShell window:

```powershell
cd C:\page\frontend
$env:NEXT_PUBLIC_API_BASE_URL = "http://127.0.0.1:8001"
npm run dev -- --hostname 127.0.0.1 --port 3001
```

Open `http://127.0.0.1:3001/workspace/projects/new`. In development mode the
backend supplies the local seller session and workspace. The project form must
show at least one local brand before running the matrix.

## Six-path headed matrix

| input mode | channel | review density | safe input |
| --- | --- | --- | --- |
| `owned_product_url` | `smartstore` | Quick | local fixture URL |
| `owned_product_url` | `coupang` | Expert | local fixture URL |
| `photo_only` | `smartstore` | Quick | browser-generated seller-owned PNGs |
| `photo_only` | `coupang` | Expert | browser-generated seller-owned PNGs |
| `manual` | `smartstore` | Quick | generic local seller facts |
| `manual` | `coupang` | Expert | generic local seller facts |

Run each input-mode pair in one visible browser, serially. Each path creates
three export jobs, while the development workspace keeps the production-like
10-export/hour limit. Wait for that rolling window to clear between pairs;
do not edit export timestamps or bypass the limiter.

```powershell
cd C:\page\frontend
$env:SELLFORM_E2E_REAL_BACKEND = "1"
$env:SELLFORM_E2E_EXTERNAL_SERVER = "1"
$env:SELLFORM_E2E_PORT = "3001"
$env:SELLFORM_LG14_SOURCE_FIXTURE_URL = "http://localhost:4177/lg14-owned-product.html"
npx playwright test e2e/lg14-real-service-six-path.spec.ts --headed --workers=1 --grep "owned_product_url"
# Wait until the development workspace export window has cleared.
npx playwright test e2e/lg14-real-service-six-path.spec.ts --headed --workers=1 --grep "photo_only"
# Wait until the development workspace export window has cleared.
npx playwright test e2e/lg14-real-service-six-path.spec.ts --headed --workers=1 --grep "manual"
```

The harness performs these seller actions through the UI:

1. Create a fresh project, select input mode, Quick/Expert density, and one
   channel.
2. Submit the manual text, generated photo upload, or localhost URL.
3. Answer each displayed seller confirmation; reject prohibited inferences and
   confirm only seller-known values/rights.
4. Continue to planning, refresh the three canonical storyboard candidates,
   and approve the storyboard.
5. Approve the existing cost plan when shown. For photo-only, select and
   approve the seller-owned image in image review.
6. Resolve remaining review cards until the Quality Bar is visible.
7. Promote the current page, generate standalone HTML/ZIP, and download the
   selected channel's PNG and JPG.
8. Reload both planning and final preview, then enter the saved direct preview
   URL again.

Each test must finish as `passed`; a skipped owned-URL path is not acceptance.

## Expected persisted result

For every path, PostgreSQL must show:

- one run/thread identity with a checkpoint and positive event sequence;
- matching workspace/project/run scope for Source, Truth, Confirmation,
  Creative Brief, CommerceCreativeMaster, QA report, and promotion;
- the latest Master references the same Source, Truth, Confirmation, and Brief;
- one current frozen DetailPageVersion and Quality Bar `PASS`;
- promotion authorizes only the selected channel;
- HTML, JPG, PNG, and ZIP artifacts all reference that page version;
- no duplicate semantic event or provider dispatch after replay.

Use the project/run IDs attached as `lg14-path-evidence` by Playwright. A
read-only spot check is:

```powershell
docker exec sellform-postgres-test psql -U sellform_test -d sellform_test -P pager=off -c `
  "SELECT id,status,current_stage,graph_thread_id,graph_checkpoint_id,last_applied_event_sequence FROM agent_runs WHERE id='<run-id>';"
docker exec sellform-postgres-test psql -U sellform_test -d sellform_test -P pager=off -c `
  "SELECT artifact_type,version_id FROM export_artifacts WHERE project_id='<project-id>' ORDER BY artifact_type;"
```

## Focused regression and build

Stop the E2E backend before tests that invoke `run_image_worker_batch`
directly; otherwise its background worker can legitimately claim the test
outbox first. Keep both database URLs fixed to the local test database.

```powershell
cd C:\page\backend
$env:SELLFORM_ALLOW_TEST_DATABASE = "1"
$env:TEST_DATABASE_URL = "postgresql+psycopg://sellform_test:test-only-password@127.0.0.1:5433/sellform_test"
$env:DATABASE_URL = $env:TEST_DATABASE_URL
$env:SELLFORM_LANGGRAPH_CHECKPOINT_DATABASE_URL = $env:TEST_DATABASE_URL
$env:SELLFORM_IMAGE_GENERATION_MODE = "mock"
$env:SELLFORM_GENERATION_MODE = "mock"
$env:SELLFORM_IMAGE_WORKER_ENABLED = "false"
.\.venv\Scripts\python.exe -m pytest tests/test_lg12_fake_quality_gate_postgres.py -q --basetemp C:\page\.runtime\pytest-lg14-runbook

cd C:\page\frontend
npm run build
```

Run only focused groups during iteration; do not use the full backend suite as
the acceptance shortcut.

## PASS criteria and cleanup

PASS requires 6/6 headed paths, PostgreSQL lineage/channel/version parity,
actual non-empty HTML/JPG/PNG/ZIP downloads, reload/direct-URL restoration,
critical/serious axe violations `0`, focused regressions green, and a fresh
frontend build exit code `0`. Legacy writers, production Supabase mutations,
and external provider calls must remain `0`.

After evidence capture, stop the fixture, frontend, and backend with `Ctrl+C`.
Do not delete user files or reset the working tree. Keep the PostgreSQL
container/data when review evidence is still needed; later fixture cleanup must
target only IDs created by this acceptance run.
