---
title: "Phase 1: Foundation — Implementation Plan"
status: active
created: 2026-06-02
origin: docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/UI_UX_WORKFLOW.md
---

# Phase 1: Foundation — Implementation Plan

## Problem Frame

Build the minimum infrastructure so a user can add a website, crawl it, and see the page inventory in a working UI. No agent intelligence, no LLM calls, no integrations — just the plumbing.

## Scope Boundary

**In scope:**
- Monorepo setup (frontend/ + backend/)
- PostgreSQL with 4 tables (sites, pages, crawl_snapshots, job_queue)
- FastAPI service with site CRUD and crawl endpoint
- Crawl4AI integration (fetch pages, extract metadata)
- Next.js app with 3 screens (Dashboard, Site Detail, Add Site)
- NextAuth.js single-user auth
- Railway deployment

**Out of scope:**
- Agent intelligence (no LLM calls)
- Issue detection / analysis
- Search Console / GA4 integrations
- Scheduling / cron triggers
- Docker / containerization
- Redis / Celery

## Implementation Units

---

### Unit 1: Monorepo Scaffold

**What:** Set up the project structure, package managers, and basic configs.

**Files to create:**
- `frontend/package.json`
- `frontend/tsconfig.json`
- `frontend/next.config.js`
- `frontend/tailwind.config.ts`
- `frontend/app/layout.tsx`
- `frontend/app/page.tsx`
- `frontend/.env.example`
- `backend/requirements.txt`
- `backend/app/__init__.py`
- `backend/app/main.py`
- `backend/app/config.py`
- `backend/.env.example`
- `.gitignore`
- `README.md`

**Decisions:**
- Python 3.11+ for backend (LangGraph requires it)
- Node 20 LTS for frontend
- pnpm for frontend package management (fast, strict)
- Poetry or pip for backend (use pip + requirements.txt for simplicity)

**Dependencies (frontend):**
- next@14, react@18, typescript, tailwindcss, @shadcn/ui setup
- next-auth, swr

**Dependencies (backend):**
- fastapi, uvicorn, sqlalchemy[asyncio], asyncpg, alembic
- pydantic, python-dotenv
- crawl4ai (for Unit 4)

**Test file:** None (scaffold only — verified by successful startup)

**Acceptance:**
- `cd frontend && pnpm dev` → Next.js runs on localhost:3000
- `cd backend && uvicorn app.main:app --reload` → FastAPI runs on localhost:8000
- `/api/health` returns `{"status": "ok"}` on both services

---

### Unit 2: Database Schema + Migrations

**What:** Create PostgreSQL tables and Alembic migration setup.

**Files to create:**
- `backend/app/database.py` (async engine, session factory)
- `backend/app/models/__init__.py`
- `backend/app/models/site.py`
- `backend/app/models/page.py`
- `backend/app/models/crawl_snapshot.py`
- `backend/app/models/job_queue.py`
- `backend/migrations/env.py`
- `backend/migrations/versions/001_initial.py`
- `backend/alembic.ini`

**Decisions:**
- Use async SQLAlchemy (asyncpg driver) — matches FastAPI's async nature
- UUIDs as primary keys (gen_random_uuid() in PostgreSQL)
- JSONB columns for flexible metadata (page.meta, crawl_snapshot.extracted_data)
- Timestamps always TIMESTAMPTZ (timezone-aware)

**Schema:** As defined in `docs/ARCHITECTURE.md` — 4 tables: sites, pages, crawl_snapshots, job_queue.

**Test scenarios:**
- Migration runs cleanly on empty database
- All tables created with correct columns and constraints
- UNIQUE constraint on (site_id, path) for pages table
- CASCADE delete from sites removes pages and snapshots
- JSONB columns accept and return Python dicts

**Test file:** `backend/tests/test_models.py`

**Acceptance:**
- `alembic upgrade head` runs without errors
- All 4 tables exist with correct schema
- Foreign keys and constraints verified

---

### Unit 3: Site CRUD API

**What:** FastAPI routes for creating, listing, reading, and deleting sites.

**Files to create:**
- `backend/app/routers/__init__.py`
- `backend/app/routers/sites.py`
- `backend/app/schemas/__init__.py`
- `backend/app/schemas/site.py` (Pydantic request/response models)
- `backend/app/services/__init__.py`
- `backend/app/services/site_service.py`

**Endpoints:**
```
POST   /sites        → Create site (domain, name)
GET    /sites        → List all sites
GET    /sites/{id}   → Get site detail with page count
DELETE /sites/{id}   → Delete site (cascades)
```

**Decisions:**
- Validate domain format on create (must be valid URL)
- Deduplicate: reject if domain already exists (409 Conflict)
- Return aggregated page_count and issue_count on detail (join query)
- Use dependency injection for database session

**Test scenarios:**
- Create site with valid domain → 201, returns site object
- Create site with duplicate domain → 409
- Create site with invalid domain → 422
- List sites → returns array, empty when none exist
- Get site by ID → returns detail with page_count
- Get non-existent site → 404
- Delete site → 204, cascades to pages

**Test file:** `backend/tests/test_sites_api.py`

**Acceptance:**
- All endpoints respond correctly to valid and invalid inputs
- Domain validation catches bad URLs
- Cascade delete verified

---

### Unit 4: Crawler Integration (Crawl4AI)

**What:** Service that crawls a given domain, extracts page metadata, and stores results.

**Files to create:**
- `backend/app/services/crawler.py`
- `backend/app/routers/crawl.py`
- `backend/app/services/job_processor.py` (simple background worker)

**Behavior:**
1. Accept site_id + domain
2. Fetch sitemap.xml (if available) to discover URLs
3. Fall back to homepage + follow internal links (BFS, max depth 3)
4. For each page (max 100):
   - Fetch HTML
   - Extract: title, meta description, H1, word count, status code, response time
   - Extract: internal links, images, canonical URL
   - Store page record + crawl_snapshot
5. Track progress (pages crawled / total discovered)
6. Use job_queue table for async processing

**Decisions:**
- Max 100 pages per crawl (configurable per site)
- Rate limit: 1 request/second to target domain (respect the site)
- Respect robots.txt (skip disallowed paths)
- Store HTML hash (SHA-256) not full HTML (saves space, detects changes)
- Crawl is async — API returns job ID, frontend polls for status

**Endpoint:**
```
POST /crawl/site     → Start crawl job (returns job_id)
GET  /crawl/{job_id} → Get crawl status (progress, errors)
```

**Test scenarios:**
- Crawl valid domain → discovers and stores pages
- Crawl respects max page limit (stops at 100)
- Crawl respects robots.txt disallow rules
- Crawl handles 404/500 responses gracefully (logs, continues)
- Crawl handles timeout (marks page as failed, continues)
- Crawl extracts correct metadata from HTML
- Progress endpoint returns current count / total
- Duplicate URLs are not re-crawled in same run

**Test file:** `backend/tests/test_crawler.py`

**Acceptance:**
- Can crawl a real site and store ≥10 pages with metadata
- Rate limiting verified (no faster than 1/sec)
- Progress tracking works end-to-end
- Errors don't crash the full crawl

---

### Unit 5: NextAuth.js Authentication

**What:** Simple single-user auth so the app isn't publicly accessible.

**Files to create:**
- `frontend/app/api/auth/[...nextauth]/route.ts`
- `frontend/lib/auth.ts` (auth config)
- `frontend/middleware.ts` (protect all routes)
- `frontend/components/auth/sign-in-form.tsx`
- `frontend/app/login/page.tsx`

**Decisions:**
- Credentials provider only (email + password stored in env vars)
- Single user — no registration, no database-backed users
- JWT session strategy (no session DB needed)
- All routes except /login protected by middleware
- API routes pass session token to backend (for future validation)

**Test scenarios:**
- Valid credentials → redirect to dashboard
- Invalid credentials → error message, stay on login
- Unauthenticated request to any route → redirect to /login
- Session persists across page reloads
- Sign out → clears session, redirects to login

**Test file:** `frontend/__tests__/auth.test.ts`

**Acceptance:**
- Cannot access dashboard without signing in
- Sign in with configured credentials works
- Sign out clears session

---

### Unit 6: Frontend — Dashboard + Site Cards

**What:** Main dashboard showing sites overview and empty states.

**Files to create:**
- `frontend/app/page.tsx` (Dashboard)
- `frontend/components/dashboard/site-card.tsx`
- `frontend/components/dashboard/empty-state.tsx`
- `frontend/components/ui/` (shadcn: card, badge, button, skeleton)
- `frontend/lib/api.ts` (backend API client)

**Behavior:**
- Fetches sites from backend via `/api/sites` BFF route
- Shows SiteCard for each site (domain, page count, status)
- Empty state: "Add your first site to get started" + CTA button
- Loading state: skeleton cards
- Error state: toast with retry

**Data flow:**
```
Dashboard → /api/sites (Next.js BFF) → FastAPI /sites → PostgreSQL
```

**Test scenarios:**
- Dashboard renders with no sites (shows empty state)
- Dashboard renders with 2+ sites (shows cards)
- Loading state shows skeletons
- API error shows error state with retry
- Site card shows correct page count

**Test file:** `frontend/__tests__/dashboard.test.tsx`

**Acceptance:**
- Dashboard loads and displays site cards from real backend data
- Empty state is user-friendly with clear action

---

### Unit 7: Frontend — Add Site Flow

**What:** Two-step onboarding: enter domain → validate → start crawl → show progress.

**Files to create:**
- `frontend/app/sites/new/page.tsx`
- `frontend/components/sites/add-site-form.tsx`
- `frontend/components/sites/crawl-progress.tsx`
- `frontend/app/api/sites/route.ts` (BFF proxy)
- `frontend/app/api/crawl/route.ts` (BFF proxy)

**Behavior:**
1. Step 1: Enter domain + optional name → validate (check reachability)
2. Step 2: Show validation results → confirm crawl settings → start
3. Step 3: Show crawl progress (poll every 2s) → redirect when done

**Decisions:**
- Domain validation happens server-side (BFF calls backend)
- Crawl progress via polling (not WebSocket — simpler for MVP)
- Poll interval: 2 seconds
- Auto-redirect to site detail when crawl completes

**Test scenarios:**
- Valid domain passes validation
- Invalid/unreachable domain shows error
- Crawl starts and progress updates render
- Completed crawl redirects to site detail
- Cancel/back during crawl doesn't crash

**Test file:** `frontend/__tests__/add-site.test.tsx`

**Acceptance:**
- Full flow: enter domain → validate → crawl → see results in site detail

---

### Unit 8: Frontend — Site Detail (Pages Tab)

**What:** Detail page showing site info and crawled pages table.

**Files to create:**
- `frontend/app/sites/[id]/page.tsx`
- `frontend/components/sites/site-header.tsx`
- `frontend/components/sites/stat-cards.tsx`
- `frontend/components/sites/pages-table.tsx`
- `frontend/app/api/sites/[id]/route.ts` (BFF)
- `frontend/app/api/sites/[id]/pages/route.ts` (BFF)

**Behavior:**
- Header: domain name, back button, "Run Agent" button (disabled/no-op in Phase 1)
- Stat cards: page count, crawl status, last crawled timestamp
- Pages table: URL, title, status code, response time, word count
- Sortable by any column
- Paginated (20 per page)

**Decisions:**
- No tabs yet (Issues and Agent Runs tabs come in Phase 2)
- Pagination server-side (backend supports ?page=&limit=)
- "Run Agent" button exists but is disabled with tooltip "Coming in Phase 2"

**Backend endpoint needed:**
```
GET /sites/{id}/pages?page=1&limit=20&sort=url&order=asc
```

**File to update:** `backend/app/routers/sites.py` (add pages sub-route)

**Test scenarios:**
- Site detail loads with correct stats
- Pages table shows crawled pages
- Pagination works (next/prev)
- Sorting works on each column
- Non-existent site → 404 page

**Test file:** `frontend/__tests__/site-detail.test.tsx`

**Acceptance:**
- Site detail shows real crawled page data
- Table is usable with 50+ pages

---

### Unit 9: Deployment to Railway

**What:** Deploy both services + PostgreSQL to Railway.

**Files to create:**
- `frontend/Dockerfile` (optional — Railway auto-detects Next.js)
- `backend/Procfile` or `railway.toml`
- `frontend/.env.production.example`
- `backend/.env.production.example`

**Steps:**
1. Create Railway project with 3 services (Next.js, FastAPI, PostgreSQL)
2. Configure environment variables (DATABASE_URL, NEXTAUTH_SECRET, etc.)
3. Connect GitHub repo for auto-deploy
4. Run migrations on first deploy
5. Verify all endpoints work via public URL

**Decisions:**
- Railway auto-detects Next.js and Python services
- PostgreSQL provisioned via Railway plugin
- Environment variables set in Railway dashboard (not committed)
- Custom domain optional (use Railway's *.up.railway.app for MVP)

**Test scenarios:**
- Frontend loads at public URL
- Auth flow works in production
- Backend health check responds
- Can add a site and crawl it end-to-end in production

**Acceptance:**
- Product accessible via URL
- Full user flow works: sign in → add site → crawl → view pages

---

## Implementation Sequence

```
Unit 1 (Scaffold) ──────────────────────┐
                                         │
Unit 2 (Database) ──────────────────────┤ (parallel with Unit 1)
                                         │
Unit 5 (Auth) ──────────────────────────┤ (parallel, depends on Unit 1)
                                         │
         ┌───────────────────────────────┘
         ▼
Unit 3 (Site CRUD) ──── depends on Unit 1 + 2
         │
         ▼
Unit 4 (Crawler) ──── depends on Unit 2 + 3
         │
         ▼
Unit 6 (Dashboard) ──── depends on Unit 3 + 5
         │
         ▼
Unit 7 (Add Site) ──── depends on Unit 4 + 6
         │
         ▼
Unit 8 (Site Detail) ──── depends on Unit 4 + 6
         │
         ▼
Unit 9 (Deploy) ──── depends on all above
```

**Parallelization opportunities:**
- Units 1, 2, 5 can start simultaneously
- Units 6, 7, 8 can be partially parallelized (shared components)

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Crawl4AI setup complexity on Windows | Blocks Unit 4 | Test in WSL2 if native install fails; document setup |
| Railway free tier limits | Can't deploy | Switch to Render (similar DX, generous free tier) |
| Async SQLAlchemy complexity | Slows Unit 2-3 | Fallback to sync SQLAlchemy if async causes problems |
| Next.js 14 App Router SSR issues | Frontend bugs | Use client components where SSR complicates things |
| Cross-origin between Next.js and FastAPI | Auth/CORS issues | BFF pattern eliminates this (frontend never calls backend directly) |

---

## Environment Prerequisites

Before starting implementation, verify:

- [ ] Node.js 20+ installed (`node --version`)
- [ ] Python 3.11+ installed (`python --version`)
- [ ] PostgreSQL 16 running locally (or use Railway dev DB)
- [ ] pnpm installed (`pnpm --version`)
- [ ] Git initialized in workspace

---

## Definition of Done (Phase 1 Complete)

- [ ] User can sign in with configured credentials
- [ ] User can add a site by entering a domain
- [ ] Domain gets validated (reachability check)
- [ ] Site gets crawled (max 100 pages, respects robots.txt)
- [ ] Crawl progress visible in real-time
- [ ] Dashboard shows all sites with page counts
- [ ] Site detail shows pages table with metadata
- [ ] Deployed to Railway and accessible via URL
- [ ] All tests pass (backend + frontend)
