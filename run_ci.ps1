# Sellform Local CI Verification Script
$ErrorActionPreference = "Stop"

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "Starting Local CI Verification..." -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

# 1. Verify Backend
Write-Host "`n[1/2] Verifying Backend (pytest)..." -ForegroundColor Yellow
try {
    Push-Location backend
    uv run pytest
    Pop-Location
    Write-Host "✓ Backend tests passed successfully." -ForegroundColor Green
} catch {
    Pop-Location
    Write-Error "✗ Backend verification failed. Please check the logs."
    Exit 1
}

# 2. Verify Frontend
Write-Host "`n[2/2] Verifying Frontend (Next.js build)..." -ForegroundColor Yellow
try {
    Push-Location frontend
    npm.cmd run build
    Pop-Location
    Write-Host "✓ Frontend build completed successfully." -ForegroundColor Green
} catch {
    Pop-Location
    Write-Error "✗ Frontend build failed. Please check TypeScript or build logs."
    Exit 1
}

Write-Host "`n=============================================" -ForegroundColor Green
Write-Host "✓ All local CI checks passed successfully!" -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
