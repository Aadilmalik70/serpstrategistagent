# SERP Strategist Agent - Local Testing Setup
# Run this script in PowerShell (as Administrator for PostgreSQL steps)

Write-Host "=== SERP Strategist Agent - Local Setup ===" -ForegroundColor Cyan
Write-Host ""

# Step 1: Check PostgreSQL
Write-Host "[1/6] Checking PostgreSQL..." -ForegroundColor Yellow
$pgBin = "C:\Program Files\PostgreSQL\16\bin"
if (-not (Test-Path "$pgBin\psql.exe")) {
    Write-Host "ERROR: PostgreSQL 16 not found at $pgBin" -ForegroundColor Red
    Write-Host "Please install PostgreSQL 16 from: https://www.postgresql.org/download/windows/" -ForegroundColor Red
    Write-Host "During installation:" -ForegroundColor Yellow
    Write-Host "  - Set superuser password to: postgres" -ForegroundColor White
    Write-Host "  - Keep default port: 5432" -ForegroundColor White
    Write-Host "  - Keep default locale" -ForegroundColor White
    Write-Host ""
    Write-Host "After installing, re-run this script." -ForegroundColor Yellow
    exit 1
}
$env:Path = "$pgBin;$env:Path"
Write-Host "  PostgreSQL found: $(psql --version)" -ForegroundColor Green

# Step 2: Check PostgreSQL service
Write-Host "[2/6] Checking PostgreSQL service..." -ForegroundColor Yellow
$pgService = Get-Service | Where-Object { $_.Name -like "*postgresql*" -or $_.DisplayName -like "*PostgreSQL*" }
if (-not $pgService) {
    Write-Host "  WARNING: PostgreSQL service not found. Checking if server is running..." -ForegroundColor Yellow
    $pgRunning = Test-NetConnection -ComputerName localhost -Port 5432 -WarningAction SilentlyContinue
    if (-not $pgRunning.TcpTestSucceeded) {
        Write-Host "  ERROR: PostgreSQL is not running on port 5432" -ForegroundColor Red
        Write-Host "  Start it manually: pg_ctl start -D `"C:\Program Files\PostgreSQL\16\data`"" -ForegroundColor White
        exit 1
    }
} else {
    if ($pgService.Status -ne "Running") {
        Write-Host "  Starting PostgreSQL service..." -ForegroundColor Yellow
        Start-Service $pgService.Name
    }
    Write-Host "  PostgreSQL service is running" -ForegroundColor Green
}

# Step 3: Create database
Write-Host "[3/6] Creating database 'serpstrategist'..." -ForegroundColor Yellow
$env:PGPASSWORD = "postgres"
$dbExists = psql -U postgres -h localhost -tc "SELECT 1 FROM pg_database WHERE datname='serpstrategist'" 2>$null
if ($dbExists -match "1") {
    Write-Host "  Database already exists" -ForegroundColor Green
} else {
    psql -U postgres -h localhost -c "CREATE DATABASE serpstrategist;" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  Database created successfully" -ForegroundColor Green
    } else {
        Write-Host "  ERROR: Failed to create database. Check password (expected: postgres)" -ForegroundColor Red
        exit 1
    }
}

# Step 4: Run migrations
Write-Host "[4/6] Running database migrations..." -ForegroundColor Yellow
Push-Location "$PSScriptRoot\backend"
if (-not (Test-Path ".venv")) {
    Write-Host "  Creating Python virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
}
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -q 2>$null
alembic upgrade head
if ($LASTEXITCODE -eq 0) {
    Write-Host "  Migrations applied successfully" -ForegroundColor Green
} else {
    Write-Host "  ERROR: Migration failed" -ForegroundColor Red
    Pop-Location
    exit 1
}
Pop-Location

# Step 5: Check frontend dependencies
Write-Host "[5/6] Checking frontend dependencies..." -ForegroundColor Yellow
Push-Location "$PSScriptRoot\frontend"
if (-not (Test-Path "node_modules")) {
    Write-Host "  Installing frontend dependencies..." -ForegroundColor Yellow
    pnpm install
}
Pop-Location
Write-Host "  Frontend dependencies ready" -ForegroundColor Green

# Step 6: Done
Write-Host ""
Write-Host "=== Setup Complete! ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "To start the app, open TWO terminals:" -ForegroundColor White
Write-Host ""
Write-Host "  Terminal 1 (Backend):" -ForegroundColor Yellow
Write-Host "    cd backend" -ForegroundColor White
Write-Host "    .\.venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host "    uvicorn app.main:app --reload --port 8000" -ForegroundColor White
Write-Host ""
Write-Host "  Terminal 2 (Frontend):" -ForegroundColor Yellow
Write-Host "    cd frontend" -ForegroundColor White
Write-Host "    pnpm dev" -ForegroundColor White
Write-Host ""
Write-Host "Then open: http://localhost:3000" -ForegroundColor Cyan
Write-Host "Login with: admin@serpstrategist.com / admin123" -ForegroundColor Cyan
Write-Host ""
Write-Host "Test flow:" -ForegroundColor White
Write-Host "  1. Login at /login" -ForegroundColor White
Write-Host "  2. Click 'Add Site' and enter a domain (e.g., example.com)" -ForegroundColor White
Write-Host "  3. Watch the crawl progress" -ForegroundColor White
Write-Host "  4. View the site detail page with crawled pages" -ForegroundColor White
