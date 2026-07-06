param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8001,
    [string]$DatabaseUrl = "postgresql://sellform:sellformpassword@localhost:5544/sellform_dev"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $repoRoot "backend"
$uvicornPath = Join-Path $backendDir ".venv\Scripts\uvicorn.exe"

if (-not (Test-Path -LiteralPath $uvicornPath)) {
    Write-Error "Backend virtualenv was not found: $uvicornPath"
}

$portPattern = ":$Port"
$existing = cmd /c "netstat -ano | findstr `"$portPattern`" | findstr `"LISTENING`"" 2>$null
if ($existing) {
    Write-Host "Port $Port is already in use. Stop that process first, then rerun this script." -ForegroundColor Yellow
    Write-Host $existing
    Write-Host ""
    Write-Host "If the PID is a stale/elevated Python process, open Administrator PowerShell and run:" -ForegroundColor Yellow
    Write-Host "  taskkill /PID <PID> /F" -ForegroundColor Cyan
    exit 1
}

Set-Location $backendDir

try {
    $tcpClient = New-Object System.Net.Sockets.TcpClient
    $connectTask = $tcpClient.ConnectAsync("127.0.0.1", 5544)
    if (-not $connectTask.Wait(1500)) {
        throw "PostgreSQL connection timeout"
    }
    $tcpClient.Close()
} catch {
    Write-Host "PostgreSQL is not reachable on localhost:5544." -ForegroundColor Yellow
    Write-Host "Start the database first, then rerun this script:" -ForegroundColor Yellow
    Write-Host "  docker compose up -d db" -ForegroundColor Cyan
    exit 1
}

$env:DATABASE_URL = $DatabaseUrl

Write-Host "Starting Sellform backend" -ForegroundColor Green
Write-Host "  URL:      http://$HostName`:$Port"
Write-Host "  Database: $DatabaseUrl"
Write-Host ""

& $uvicornPath src.app:app --host $HostName --port $Port
