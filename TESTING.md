# Local Testing Guide

## Prerequisites

### Install PostgreSQL 16 (one-time)

**Option A: GUI Installer (Recommended)**
1. Download from https://www.postgresql.org/download/windows/
2. Run the installer **as Administrator**
3. Set superuser password to: `postgres`
4. Keep port: `5432`
5. Keep default locale and data directory
6. Uncheck "Launch Stack Builder" at the end

**Option B: winget (from Admin PowerShell)**
```powershell
winget install -e --id PostgreSQL.PostgreSQL.16 --override "--mode unattended --superpassword postgres --serverport 5432"
```

### Verify Installation
```powershell
# Add to PATH (if not already)
$env:Path = "C:\Program Files\PostgreSQL\16\bin;$env:Path"
psql --version
# Should show: psql (PostgreSQL) 16.x
```

---

## Quick Start (after PostgreSQL is installed)

### Automated Setup
```powershell
# Run from project root (as Admin for service access)
.\setup-local.ps1
```

### Manual Setup

#### 1. Create Database
```powershell
$env:Path = "C:\pgsql\bin;$env:Path"
psql -U postgres -h localhost -p 5433 -c "CREATE DATABASE serpstrategist;"
```

#### 2. Run Migrations
```powershell
cd backend
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "."
alembic upgrade head
```

#### 3. Start Backend (Terminal 1)
```powershell
cd backend
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "."
uvicorn app.main:app --reload --port 8000
```

#### 4. Start Frontend (Terminal 2)
```powershell
cd frontend
pnpm dev
```

---

## Testing the Full Flow

1. **Open** http://localhost:3000
2. **Login** with: `admin@serpstrategist.com` / `admin123`
3. **Add Site**: Click "Add Site" → enter `example.com` → submit
4. **Watch Crawl**: Progress bar updates as pages are crawled
5. **View Results**: After crawl completes, click the site to see pages

### API Endpoints (test directly)

```bash
# Health check
curl http://localhost:8000/health

# List sites
curl http://localhost:8000/sites

# Create site
curl -X POST http://localhost:8000/sites -H "Content-Type: application/json" -d '{"domain": "example.com", "name": "Example"}'
```

---

## Environment Files

Already configured in:
- `backend/.env` — Database URL, secret key, CORS
- `frontend/.env` — NextAuth, auth credentials, API URL

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `psql` not found | Add `C:\pgsql\bin` to PATH |
| Connection refused on 5433 | Start PostgreSQL: `C:\pgsql\bin\pg_ctl start -D C:\pgsql\data -l C:\pgsql\logfile.txt -o "-p 5433"` |
| Permission denied (migrations) | Check DATABASE_URL in `backend/.env` matches your password |
| Frontend can't reach backend | Ensure backend is running on port 8000 |
| Login doesn't work | Check AUTH_EMAIL/AUTH_PASSWORD in `frontend/.env` |
