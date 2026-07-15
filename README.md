# SERP Strategist Agent

Autonomous Search Growth Agent that continuously improves a website's SEO and GEO performance.

## Architecture

- **Frontend:** Next.js 16 (App Router) + Tailwind CSS + NextAuth.js
- **Backend:** FastAPI + SQLAlchemy (async) + PostgreSQL
- **Crawl runtime:** durable PostgreSQL jobs and URL frontier with Redis wake-up
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

Set `CRAWL_WORKER_ENABLED=true` on the API/worker service. Crawl requests are
persisted and will remain queued when no crawl worker is enabled; API background
tasks do not execute crawls.

For the first production rollout of migration `018`, use a two-step cutover:
deploy the schema and application with `CRAWL_WORKER_ENABLED=false`, wait until
the previous API replicas and their in-process crawls have stopped, then enable
the durable worker and redeploy. This prevents a legacy background crawl and a
new leased worker from processing the same migrated job during a rolling deploy.

The backend image includes an opt-in sandboxed Chromium runtime for bounded
JavaScript fallback crawling. Rendering defaults off. Enable it only after the
target worker passes its startup sandbox check and has explicit memory/CPU/PID
limits. It runs as an unprivileged user, renders the already byte-bounded source,
pins the audited hostname to its validated public IP, blocks WebSockets and
cross-origin browser requests, and never attempts to solve or bypass WAF
challenges. Configure the render caps with `CRAWLER_RENDER_MAX_PAGES` and
`CRAWLER_DEVICE_COMPARE_MAX_PAGES`.

Search Console ingestion uses the same PostgreSQL-first lease model. Set
`SEARCH_SYNC_WORKER_ENABLED=true` on one worker service after migration `019` is
applied. `SCHEDULER_ENABLED=true` creates daily jobs; the worker persists
query/page/day metrics in day-sized partitions and commits the full lookback
atomically. The default three-day finalization lag avoids treating fresh,
unfinished GSC data as complete. It reconciles at most
`SEARCH_OPPORTUNITY_ACTION_LIMIT` top findings into simulation-only governed
draft actions. Daily and whole-job row caps bound database/WAL cost, and a
completed sync is reused for 24 hours by default. Only real (non-simulation)
executions maintain 7/14/30/60/90-day measurement windows or influence learning.
Redis remains an optional bounded wake-up hint, not the source of truth.

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
