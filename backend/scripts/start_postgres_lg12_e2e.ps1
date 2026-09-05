param(
    [ValidateSet("migrate", "backend")]
    [string]$Mode = "migrate"
)

$ErrorActionPreference = "Stop"
$TestUrl = "postgresql+psycopg://sellform_test:test-only-password@127.0.0.1:5433/sellform_test"

# This wrapper is deliberately explicit.  It cannot select a Supabase or
# ordinary local-dev URL, and every child command inherits one PG database for
# ORM persistence and LangGraph checkpoints.
$env:APP_ENV = "test"
$env:SELLFORM_ALLOW_TEST_DATABASE = "1"
$env:TEST_DATABASE_URL = $TestUrl
$env:E2E_DATABASE_URL = $TestUrl
$env:DATABASE_URL = $TestUrl
$env:SELLFORM_LANGGRAPH_CHECKPOINT_DATABASE_URL = $TestUrl
$env:SELLFORM_IMAGE_WORKER_ENABLED = "false"

docker compose -f ..\docker-compose.postgres-test.yml up -d postgres-test
if ($LASTEXITCODE -ne 0) { throw "Local PostgreSQL test container did not start." }

$deadline = (Get-Date).AddSeconds(60)
$ready = $false
while ((Get-Date) -lt $deadline) {
    $health = docker inspect --format '{{.State.Health.Status}}' sellform-postgres-test 2>$null
    if ($health -eq "healthy") {
        try {
            .\.venv\Scripts\python.exe -c "from sqlalchemy import create_engine, text; import os; create_engine(os.environ['TEST_DATABASE_URL']).connect().execute(text('SELECT 1'))"
            if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        } catch {}
    }
    Start-Sleep -Seconds 1
}
if (-not $ready) {
    Write-Error "PostgreSQL test DB was not ready; migrations were not run. target=localhost:5433/sellform_test health=$health"
    docker compose -f ..\docker-compose.postgres-test.yml ps
    docker logs --tail 50 sellform-postgres-test
    exit 1
}

if ($Mode -eq "migrate") {
    .\.venv\Scripts\python.exe -m scripts.run_postgres_test_migrations
    exit $LASTEXITCODE
}

.\.venv\Scripts\python.exe -m uvicorn src.app:app --host 127.0.0.1 --port 8001
