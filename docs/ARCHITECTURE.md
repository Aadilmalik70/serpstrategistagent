# SERP Strategist Agent — System Architecture

> Last updated: 2026-06-02
> Status: v1 (fresh start)

## Design Philosophy

1. **Agent-first** — The agent producing SEO value is the product. UI is a window into what the agent does, not the product itself.
2. **Progressive complexity** — Start with the minimum viable loop. Add layers only when the previous layer proves valuable.
3. **Solo-dev friendly** — One person deploys, maintains, and extends this. No Kubernetes, no microservices, no multi-region.
4. **Earn your infrastructure** — Redis, queues, workers, caching — each earns its place by solving a real problem, not a hypothetical one.

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Frontend | Next.js 14 (App Router) | Full-stack React, SSR, API routes, great DX |
| Backend API | FastAPI (Python) | Native async, Pydantic validation, Python AI ecosystem |
| Agent Runtime | LangGraph | State machine for agent orchestration, checkpointing, human-in-the-loop |
| Database | PostgreSQL 16 | Structured data, JSON columns for flexibility, full-text search |
| Task Queue | PostgreSQL (pg_notify + polling) | Skip Redis/Celery for MVP — use Postgres as the job queue |
| LLM | Claude API (Anthropic) | Best reasoning for SEO analysis and content generation |
| Crawling | Crawl4AI | Open-source, async, handles JS rendering |
| Deployment | Railway or Render | One-click deploys, managed Postgres, no Docker required locally |
| Auth | NextAuth.js | Simple, self-hosted, supports OAuth + credentials |

### What's NOT in MVP (earn it later)

| Technology | When to Add | Trigger |
|-----------|-------------|---------|
| Redis | When job queue throughput exceeds pg_notify capacity | >100 concurrent crawl jobs |
| Celery/Bull | When background tasks need retry, priority, dead-letter | Complex scheduling needs |
| Docker | When deployment environments diverge from dev | Second developer joins or custom infra needed |
| Kubernetes | Never for this product scale | — |
| Vector DB | When memory/RAG needs exceed PostgreSQL pgvector | >100K embeddings with sub-100ms query requirement |
| CDN/S3 | When storing generated content assets | Content generation feature ships |

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        NEXT.JS APP                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │Dashboard │  │  Sites   │  │  Issues  │  │ Activity │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Next.js API Routes (BFF)                 │   │
│  │         /api/sites, /api/agent, /api/issues          │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP (internal)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      FASTAPI SERVICE                         │
│                                                              │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────┐   │
│  │  REST    │  │  Agent API   │  │  Webhook Handlers  │   │
│  │  CRUD    │  │  (trigger,   │  │  (Search Console,  │   │
│  │  Routes  │  │   status,    │  │   GA4 callbacks)   │   │
│  │          │  │   approve)   │  │                    │   │
│  └──────────┘  └──────────────┘  └────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              LANGGRAPH AGENT RUNTIME                   │   │
│  │                                                        │   │
│  │   ┌─────────┐    ┌─────────┐    ┌─────────┐         │   │
│  │   │ OBSERVE │───▶│ ANALYZE │───▶│  PLAN   │         │   │
│  │   └─────────┘    └─────────┘    └─────────┘         │   │
│  │        ▲                              │               │   │
│  │        │                              ▼               │   │
│  │   ┌─────────┐                   ┌─────────┐         │   │
│  │   │  LEARN  │◀──────────────────│ EXECUTE │         │   │
│  │   └─────────┘                   └─────────┘         │   │
│  │                                                        │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      POSTGRESQL 16                            │
│                                                              │
│  sites | pages | crawl_snapshots | issues | agent_runs      │
│                                                              │
│  + pg_notify for job queue                                   │
│  + pgvector extension (future: embeddings)                   │
└─────────────────────────────────────────────────────────────┘
```

---

## Database Schema (MVP — 6 tables)

Start with 6 tables. Not 16. Add tables when features demand them.

### Core Tables

```sql
-- The site being managed
CREATE TABLE sites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    domain VARCHAR(255) NOT NULL UNIQUE,
    status VARCHAR(50) DEFAULT 'onboarding', -- onboarding, active, paused
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Individual pages discovered by crawling
CREATE TABLE pages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id UUID REFERENCES sites(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    path VARCHAR(2048) NOT NULL,
    title VARCHAR(512),
    status VARCHAR(50) DEFAULT 'discovered', -- discovered, analyzed, optimized
    meta JSONB DEFAULT '{}', -- description, h1, word_count, schema_types, etc.
    last_crawled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(site_id, path)
);

-- Raw crawl data snapshots
CREATE TABLE crawl_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    page_id UUID REFERENCES pages(id) ON DELETE CASCADE,
    html_hash VARCHAR(64), -- detect changes without storing full HTML
    status_code INTEGER,
    response_time_ms INTEGER,
    headers JSONB,
    extracted_data JSONB, -- links, headings, images, structured data
    crawled_at TIMESTAMPTZ DEFAULT NOW()
);

-- Issues found by the agent (technical, content, opportunity)
CREATE TABLE issues (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id UUID REFERENCES sites(id) ON DELETE CASCADE,
    page_id UUID REFERENCES pages(id) ON DELETE SET NULL,
    type VARCHAR(50) NOT NULL, -- technical, content, opportunity
    severity VARCHAR(20) NOT NULL, -- critical, high, medium, low
    title VARCHAR(512) NOT NULL,
    description TEXT,
    recommendation TEXT,
    status VARCHAR(50) DEFAULT 'open', -- open, in_progress, resolved, dismissed
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Agent execution runs
CREATE TABLE agent_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id UUID REFERENCES sites(id) ON DELETE CASCADE,
    node VARCHAR(50) NOT NULL, -- observe, analyze, plan, execute, learn
    status VARCHAR(50) DEFAULT 'running', -- running, completed, failed, needs_approval
    input JSONB,
    output JSONB,
    error TEXT,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER
);

-- Simple job queue using PostgreSQL
CREATE TABLE job_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(50) DEFAULT 'pending', -- pending, processing, completed, failed
    priority INTEGER DEFAULT 0,
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    scheduled_for TIMESTAMPTZ DEFAULT NOW(),
    locked_by VARCHAR(255),
    locked_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Tables Added Later (NOT in MVP)

| Table | Added When |
|-------|-----------|
| `integrations` | When Search Console / GA4 OAuth is built |
| `tasks` | When agent can create and execute multi-step plans |
| `approvals` | When human-in-the-loop approval flow ships |
| `content_assets` | When content generation/publishing ships |
| `memory` | When agent learning/memory system ships |
| `metrics_daily` | When daily metric tracking is needed |

---

## Agent Architecture

### State Machine (LangGraph)

The agent runs as a cyclic state machine, NOT a DAG. Each node is independently triggerable.

```python
# Simplified agent graph
from langgraph.graph import StateGraph, END

class AgentState(TypedDict):
    site_id: str
    current_node: str
    observations: list      # Crawl results, metrics
    analysis: dict          # Issues found, opportunities
    plan: list              # Prioritized actions
    execution_results: list # What was done
    learnings: dict         # What worked, what didn't

graph = StateGraph(AgentState)

# Nodes
graph.add_node("observe", observe_node)    # Crawl, fetch metrics
graph.add_node("analyze", analyze_node)    # Find issues, score pages
graph.add_node("plan", plan_node)          # Prioritize, create action plan
graph.add_node("execute", execute_node)    # Apply fixes, generate content
graph.add_node("learn", learn_node)        # Evaluate results, update strategy

# Edges (cyclic)
graph.add_edge("observe", "analyze")
graph.add_edge("analyze", "plan")
graph.add_conditional_edges("plan", should_execute_or_wait)
graph.add_edge("execute", "learn")
graph.add_edge("learn", "observe")  # Loop back

graph.set_entry_point("observe")
```

### MVP: Only Observe + Analyze

For the first working version, only `observe` and `analyze` nodes run. The agent:
1. Crawls the site (max 100 pages)
2. Extracts page data (title, meta, headings, links, status codes)
3. Identifies issues (broken links, missing meta, thin content, slow pages)
4. Stores everything in the database
5. UI displays findings

No planning, no execution, no learning yet. Those earn their place.

### Agent Triggering

- **Manual:** User clicks "Run Agent" in UI
- **Scheduled:** Cron job triggers agent run every 24h (configurable)
- **Event-driven (future):** Webhook from Search Console on significant change

---

## API Design

### Next.js BFF Routes (frontend → backend)

```
GET    /api/sites              → List user's sites
POST   /api/sites              → Add new site
GET    /api/sites/:id          → Site details + summary stats
DELETE /api/sites/:id          → Remove site

GET    /api/sites/:id/pages    → Page inventory (paginated)
GET    /api/sites/:id/issues   → Issues list (filterable)
GET    /api/sites/:id/runs     → Agent run history

POST   /api/agent/run/:siteId  → Trigger agent manually
GET    /api/agent/status/:runId → Check run status
```

### FastAPI Internal Routes

```
POST   /crawl/site             → Start crawl job
GET    /crawl/status/:jobId    → Crawl progress
POST   /analyze/site           → Run analysis on crawled data
GET    /agent/run/:siteId      → Execute full agent loop
POST   /agent/approve/:runId   → Approve pending action (future)
```

---

## Data Flow (MVP)

```
User adds site
       │
       ▼
[Validate domain] → Store in `sites` table
       │
       ▼
[Trigger crawl] → Crawl4AI fetches pages (max 100)
       │
       ▼
[Store results] → `pages` + `crawl_snapshots` tables
       │
       ▼
[Run analysis] → LLM analyzes page data, finds issues
       │
       ▼
[Store issues] → `issues` table
       │
       ▼
[Display in UI] → Dashboard shows site health, issues list
```

---

## Project Structure

```
serpstrategistagent/
├── frontend/                  # Next.js 14 App
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx          # Dashboard
│   │   ├── sites/
│   │   │   ├── page.tsx      # Sites list
│   │   │   └── [id]/
│   │   │       ├── page.tsx  # Site detail
│   │   │       ├── pages/    # Page inventory
│   │   │       └── issues/   # Issues list
│   │   └── api/              # BFF routes
│   │       ├── sites/
│   │       └── agent/
│   ├── components/
│   │   ├── ui/               # Shadcn components
│   │   ├── dashboard/
│   │   └── sites/
│   ├── lib/
│   │   ├── api.ts            # Backend client
│   │   └── utils.ts
│   └── package.json
│
├── backend/                   # FastAPI Service
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── models/           # SQLAlchemy models
│   │   │   ├── site.py
│   │   │   ├── page.py
│   │   │   └── issue.py
│   │   ├── routers/          # API routes
│   │   │   ├── sites.py
│   │   │   ├── crawl.py
│   │   │   └── agent.py
│   │   ├── services/         # Business logic
│   │   │   ├── crawler.py
│   │   │   ├── analyzer.py
│   │   │   └── agent.py
│   │   └── agent/            # LangGraph agent
│   │       ├── graph.py      # State machine definition
│   │       ├── state.py      # Agent state schema
│   │       ├── nodes/
│   │       │   ├── observe.py
│   │       │   ├── analyze.py
│   │       │   ├── plan.py
│   │       │   ├── execute.py
│   │       │   └── learn.py
│   │       └── tools/        # Agent tools
│   │           ├── crawl.py
│   │           ├── search_console.py
│   │           └── content.py
│   ├── migrations/            # Alembic
│   ├── tests/
│   └── requirements.txt
│
├── docs/                      # Documentation
│   ├── ARCHITECTURE.md
│   ├── UI_UX_WORKFLOW.md
│   └── ROADMAP.md
│
├── STRATEGY.md
├── AGENTS.md
└── README.md
```

---

## Security Considerations

- **Auth:** NextAuth.js with single-user mode initially. No public registration.
- **API:** All FastAPI routes require valid session token (passed from Next.js BFF)
- **Crawling:** Rate limiting (max 1 req/sec to target sites), respect robots.txt
- **LLM:** API keys stored in environment variables, never in code
- **Database:** Parameterized queries only (SQLAlchemy handles this)
- **CORS:** Frontend origin only
- **Input validation:** Pydantic models on all API inputs

---

## Deployment (MVP)

Single deployment target: **Railway** (or Render)

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Next.js    │────▶│   FastAPI   │────▶│  PostgreSQL  │
│  (Railway)  │     │  (Railway)  │     │  (Railway)   │
└─────────────┘     └─────────────┘     └─────────────┘
```

- Next.js: Node.js service, auto-deployed from `frontend/`
- FastAPI: Python service, auto-deployed from `backend/`
- PostgreSQL: Railway managed database
- No Docker required for deployment (Railway detects frameworks)
- Environment variables managed in Railway dashboard

---

## Key Decisions Log

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| Skip Redis for MVP | Use pg_notify + polling | One less service to manage. PostgreSQL handles the load for 1-10 sites. |
| Skip Docker locally | Direct Python + Node.js | Faster iteration for solo dev. Add Docker when second dev joins or deployment differs. |
| PostgreSQL as job queue | `job_queue` table + worker | Simple, transactional, no extra infrastructure. Upgrade to Redis+Celery at scale. |
| Monorepo | `frontend/` + `backend/` | Easy to share types, deploy together, single git history. |
| Next.js BFF pattern | API routes proxy to FastAPI | Frontend calls same-origin, avoids CORS, can add caching/auth logic. |
| 6 tables not 16 | MVP-first | Add tables when features demand them, not when designing them. |
| Agent: observe+analyze only for MVP | Progressive agent | Don't build execute/learn until observe+analyze prove valuable. |
| Railway deployment | Managed PaaS | Zero-config deploys, managed Postgres, free tier available. |
