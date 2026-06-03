# Start SERP Strategist Agent - Full Local Dev
# Run this after setup-local.ps1 OR after PostgreSQL portable is ready

$ErrorActionPreference = "Stop"

# Determine PostgreSQL binary path
$pgBin = $null
if (Test-Path "C:\pgsql\bin\initdb.exe") {
    $pgBin = "C:\pgsql\bin"
} elseif (Test-Path "C:\Program Files\PostgreSQL\16\bin\initdb.exe") {
    $pgBin = "C:\Program Files\PostgreSQL\16\bin"
}

if (-not $pgBin) {
    Write-Host "ERROR: PostgreSQL binaries not found!" -ForegroundColor Red
    exit 1
}

$env:Path = "$pgBin;$env:Path"
Write-Host "Using PostgreSQL from: $pgBin" -ForegroundColor Cyan

# Data directory for portable PostgreSQL
$dataDir = "C:\pgsql\data"

# Initialize data directory if needed
if (-not (Test-Path $dataDir)) {
    Write-Host "Initializing database cluster..." -ForegroundColor Yellow
    & "$pgBin\initdb.exe" -D $dataDir -U postgres -E UTF8 --locale=C
    if ($LASTEXITCODE -ne 0) { Write-Host "initdb failed!" -ForegroundColor Red; exit 1 }
}

# Start PostgreSQL if not running
$pgRunning = $false
try {
    $conn = Test-NetConnection -ComputerName localhost -Port 5433 -WarningAction SilentlyContinue -ErrorAction SilentlyContinue
    $pgRunning = $conn.TcpTestSucceeded
} catch {}

if (-not $pgRunning) {
    Write-Host "Starting PostgreSQL..." -ForegroundColor Yellow
    Start-Process -FilePath "$pgBin\pg_ctl.exe" -ArgumentList "start", "-D", $dataDir, "-l", "C:\pgsql\logfile.txt", "-o", ""-p 5433""" -NoNewWindow -Wait
    Start-Sleep -Seconds 2
    Write-Host "PostgreSQL started" -ForegroundColor Green
} else {
    Write-Host "PostgreSQL already running on port 5433" -ForegroundColor Green
}

# Create database if not exists
$dbCheck = & "$pgBin\psql.exe" -U postgres -h localhost -p 5433 -tc "SELECT 1 FROM pg_database WHERE datname='serpstrategist'" 2>$null
if ($dbCheck -notmatch "1") {
    Write-Host "Creating database 'serpstrategist'..." -ForegroundColor Yellow
    & "$pgBin\psql.exe" -U postgres -h localhost -p 5433 -c "CREATE DATABASE serpstrategist;"
}

# Run migrations
Write-Host "Running migrations..." -ForegroundColor Yellow
Push-Location "$PSScriptRoot\backend"
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "."
alembic upgrade head
Pop-Location
Write-Host "Migrations complete" -ForegroundColor Green

# Start backend
Write-Host ""
Write-Host "Starting backend on http://localhost:8000 ..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\backend'; .\.venv\Scripts\Activate.ps1; `$env:PYTHONPATH='.'; uvicorn app.main:app --reload --port 8000"

Start-Sleep -Seconds 3

# Start frontend
Write-Host "Starting frontend on http://localhost:3000 ..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\frontend'; pnpm dev"

Write-Host ""
Write-Host "=== Both servers starting ===" -ForegroundColor Green
Write-Host "Backend:  http://localhost:8000/health" -ForegroundColor White
Write-Host "Frontend: http://localhost:3000" -ForegroundColor White
Write-Host "Login:    admin@serpstrategist.com / admin123" -ForegroundColor White
Write-Host ""
Write-Host "To stop PostgreSQL later: pg_ctl stop -D C:\pgsql\data" -ForegroundColor Gray
Write-Host "PostgreSQL running on port 5433" -ForegroundColor Gray
