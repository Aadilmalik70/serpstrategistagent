# SERP Strategist Agent — Development Roadmap

> Last updated: 2026-06-02
> Status: v1 (fresh start)

## Overview

Four phases. Each phase delivers a working, deployable product. No phase depends on completing everything in the previous phase — just the critical path items.

```
Phase 1: Foundation (see it work)
    → Can crawl a site and show results in UI

Phase 2: Intelligence (make it smart)
    → Agent analyzes crawl data and finds real issues

Phase 3: Action (make it do things)
    → Agent executes fixes and generates content

Phase 4: Autonomy (make it self-improving)
    → Agent learns from results and runs without supervision
```

---

## Phase 1: Foundation — "See it work"

**Goal:** User can add a site, crawl it, and see page inventory + basic stats in a working UI.

**Milestone:** Deploy to Railway. User adds domain → sees crawled pages within 5 minutes.

### What gets built:

| Component | Deliverable |
|-----------|------------|
| **Database** | PostgreSQL with 4 tables (sites, pages, crawl_snapshots, job_queue) |
| **Backend** | FastAPI with crawl endpoint, site CRUD, basic job processing |
| **Crawler** | Crawl4AI integration: fetch pages, extract metadata, store results |
| **Frontend** | 3 screens: Dashboard, Site Detail (pages tab only), Add Site |
| **Deployment** | Railway: Next.js + FastAPI + PostgreSQL |
| **Auth** | NextAuth.js with credentials provider (single user) |

### What does NOT get built:
- No agent intelligence (no LLM calls)
- No issue detection
- No analysis
- No Search Console / GA4 integration
- No scheduling (manual trigger only)

### Critical path:
```
1. Set up monorepo (frontend/ + backend/)
2. PostgreSQL schema + migrations
3. FastAPI: site CRUD + crawl endpoint
4. Crawl4AI: crawl a site, extract page data
5. Next.js: Add Site flow → trigger crawl
6. Next.js: Dashboard + Site Detail with real data
7. Deploy to Railway
```

### Definition of done:
- [ ] User can sign in
- [ ] User can add a site by domain
- [ ] Site gets crawled (max 100 pages)
- [ ] Pages appear in UI with title, URL, status code
- [ ] Dashboard shows site card with page count
- [ ] Deployed and accessible via URL

---

## Phase 2: Intelligence — "Make it smart"

**Goal:** Agent analyzes crawl data, identifies real SEO issues, and presents prioritized findings.

**Milestone:** Agent finds issues that a human SEO expert would also find. User says "that's actually useful."

### What gets built:

| Component | Deliverable |
|-----------|------------|
| **Database** | Add `issues` + `agent_runs` tables |
| **Agent** | LangGraph with observe + analyze nodes |
| **Analysis** | LLM-powered issue detection (technical SEO, content quality, opportunities) |
| **Frontend** | Issues tab on Site Detail, issue severity badges, agent run history |
| **Scheduling** | Cron-triggered agent runs (every 24h) |

### Issue types the agent detects:

**Technical:**
- Missing/duplicate title tags
- Missing/duplicate meta descriptions
- Broken internal links (404s)
- Slow page response time (>3s)
- Missing H1 or multiple H1s
- Missing alt text on images
- Non-HTTPS pages
- Redirect chains

**Content:**
- Thin content (<300 words)
- Missing structured data (schema.org)
- Keyword stuffing signals
- Duplicate content across pages

**Opportunities:**
- Pages with high impressions but low CTR (needs Search Console — may defer)
- Internal linking opportunities
- Content gap suggestions based on site topic

### Critical path:
```
1. Add issues + agent_runs tables
2. Build observe node (wraps existing crawler)
3. Build analyze node (LLM analyzes page data → issues)
4. Wire into LangGraph state machine
5. API: expose issues, agent runs
6. Frontend: Issues tab, severity badges, run history
7. Add cron trigger (Railway cron or pg-based scheduler)
```

### Definition of done:
- [ ] Agent runs observe+analyze automatically every 24h
- [ ] Agent produces real, actionable SEO issues
- [ ] Issues appear in UI with severity and recommendation
- [ ] User can dismiss irrelevant issues
- [ ] Agent run history shows what was analyzed and when
- [ ] Health score calculated from issue severity

---

## Phase 3: Action — "Make it do things"

**Goal:** Agent can plan fixes and execute them (with approval for high-risk actions).

**Milestone:** Agent fixes a real issue on the user's site with one click of approval.

### What gets built:

| Component | Deliverable |
|-----------|------------|
| **Agent** | Add plan + execute nodes |
| **Integrations** | WordPress REST API, GitHub API for content repos |
| **Content Gen** | LLM generates meta descriptions, title tags, content improvements |
| **Approval Flow** | Human-in-the-loop for publish/deploy actions |
| **Frontend** | Approval queue, task status, content preview |

### Actions the agent can take:

**Auto-execute (no approval needed):**
- Generate fix recommendations
- Update internal analysis
- Re-crawl pages that changed

**Requires approval:**
- Update meta descriptions on WordPress
- Publish new/updated content
- Modify schema markup
- Create redirects

### Critical path:
```
1. Build plan node (prioritize issues → create action plan)
2. Build execute node (apply fixes via integrations)
3. WordPress integration (REST API for meta/content updates)
4. Content generation (LLM writes/improves content)
5. Approval UI (queue, preview, approve/reject)
6. Connect plan→execute flow with approval gate
```

### Definition of done:
- [ ] Agent creates fix plans for detected issues
- [ ] Agent can update WordPress meta descriptions
- [ ] Agent can generate content improvements
- [ ] Approval queue shows pending actions with preview
- [ ] User can approve/reject agent actions
- [ ] Executed actions tracked and logged

---

## Phase 4: Autonomy — "Make it self-improving"

**Goal:** Agent learns from outcomes, adapts strategy, and runs with minimal human oversight.

**Milestone:** Agent demonstrates measurable ranking improvement over 30 days without manual intervention.

### What gets built:

| Component | Deliverable |
|-----------|------------|
| **Agent** | Add learn node (outcome evaluation) |
| **Integrations** | Search Console API, GA4 API |
| **Memory** | Agent memory system (what worked, what didn't) |
| **Metrics** | Daily metric tracking, trend detection |
| **Frontend** | Performance dashboard, learning log, strategy view |

### Learning capabilities:
- Track which fixes led to ranking improvements
- Identify content patterns that perform well
- Adjust priority scoring based on observed outcomes
- Report on what's working vs. not

### Critical path:
```
1. Search Console OAuth + data ingestion
2. GA4 OAuth + data ingestion
3. Build learn node (compare before/after for executed actions)
4. Memory system (store learnings, inform future decisions)
5. Daily metrics table + trend detection
6. Performance dashboard (rankings, traffic, agent effectiveness)
```

### Definition of done:
- [ ] Agent tracks outcomes of its actions
- [ ] Agent adapts priority scoring based on results
- [ ] Search Console data shown in UI
- [ ] GA4 organic traffic trend shown in UI
- [ ] Agent reports on what's working
- [ ] 30-day autonomous run with measurable improvement

---

## Phase Timeline (Estimates)

| Phase | Duration | Depends On |
|-------|----------|-----------|
| Phase 1: Foundation | 1-2 weeks | Nothing — start here |
| Phase 2: Intelligence | 1-2 weeks | Phase 1 (crawl data exists) |
| Phase 3: Action | 2-3 weeks | Phase 2 (issues identified) |
| Phase 4: Autonomy | 2-4 weeks | Phase 3 (actions executed) + real-world data |

**Total to full product: 6-11 weeks for a solo developer.**

---

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Crawl4AI can't handle JS-heavy sites | Low page coverage | Fall back to Playwright-based crawling |
| LLM analysis produces low-quality issues | Users don't trust agent | Tune prompts aggressively in Phase 2, add confidence scoring |
| WordPress API varies across hosts | Execute node fails | Start with standard WP REST API, document supported setups |
| Railway costs grow with crawl frequency | Budget pressure | Rate limit crawls, cache aggressively, monitor costs |
| Search Console API quota limits | Can't fetch enough data | Batch requests, cache for 24h, prioritize by traffic |
| Agent makes harmful changes | SEO damage | Approval gate for ALL publishing actions, staged rollout |

---

## Success Criteria (Product-Level)

| Metric | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|--------|---------|---------|---------|---------|
| Sites crawled | 1+ | 1+ | 1+ | 3+ |
| Pages indexed | 100 | 100 | 100 | 500+ |
| Issues detected | 0 | 10+ per site | 10+ | 10+ |
| Issues fixed | 0 | 0 | 5+ per month | 10+ per month |
| Ranking improvements | — | — | — | Measurable for 50%+ of optimized pages |
| Autonomous run time | 0 | 24h cycles | 24h cycles | 30 days continuous |
