# SERP Strategist Agent

Autonomous Search Growth Agent that continuously improves a website's SEO and GEO performance.

## Architecture

- **Frontend:** Next.js 16 (App Router) + Tailwind CSS + NextAuth.js
- **Backend:** FastAPI + SQLAlchemy (async) + PostgreSQL
- **Agent Runtime:** LangGraph (Phase 2)
- **Deployment:** Railway

## Quick Start

### Prerequisites

- Node.js 20+
- Python 3.11+
- PostgreSQL 16
- pnpm

### Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate  # Windows
pip install -r requirements.txt
cp .env.example .env    # Edit with your DB credentials
alembic upgrade head    # Run migrations
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
pnpm install
cp .env.example .env.local  # Edit with your credentials
pnpm dev
```

### URLs

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

## Project Structure

```
serpstrategistagent/
├── frontend/          # Next.js app
│   ├── app/           # App Router pages
│   ├── components/    # React components
│   └── lib/           # Utilities
├── backend/           # FastAPI service
│   ├── app/
│   │   ├── models/    # SQLAlchemy models
│   │   ├── routers/   # API endpoints
│   │   ├── schemas/   # Pydantic models
│   │   └── services/  # Business logic
│   └── migrations/    # Alembic migrations
└── docs/              # Architecture & planning docs
```
