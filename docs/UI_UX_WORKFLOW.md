# SERP Strategist Agent — UI/UX Workflow

> Last updated: 2026-06-02
> Status: v1 (fresh start)

## Design Philosophy

1. **Agent workspace, not SEO dashboard** — This is where you watch your agent work and review its findings. Not a manual SEO tool with 50 charts.
2. **Progressive disclosure** — Show summary first, details on demand. Don't overwhelm.
3. **Action-oriented** — Every screen answers "what should I do?" or "what did the agent do?"
4. **Minimal viable UI** — 3 screens for MVP. Add screens when features demand them.

---

## Tech Stack (UI)

| Component | Choice | Why |
|-----------|--------|-----|
| Framework | Next.js 14 App Router | SSR, file-based routing, server components |
| Styling | Tailwind CSS | Utility-first, fast iteration |
| Components | shadcn/ui | Copy-paste components, no dependency lock-in |
| Charts | Recharts | Simple, React-native charting |
| Icons | Lucide React | Clean, consistent icon set |
| State | React Server Components + SWR | Minimal client state, server-first |
| Theme | Light mode only (MVP) | One less thing to maintain |

---

## Information Architecture

### MVP: 3 Screens

```
┌─────────────────────────────────────────┐
│              DASHBOARD                   │
│  (All sites overview + agent status)    │
├─────────────────────────────────────────┤
│              SITE DETAIL                 │
│  (Single site: health, pages, issues)   │
├─────────────────────────────────────────┤
│              ADD SITE                    │
│  (Onboarding flow)                      │
└─────────────────────────────────────────┘
```

### Later Screens (NOT MVP)

| Screen | Added When |
|--------|-----------|
| Issues Detail | When agent produces fix recommendations |
| Content Editor | When content generation ships |
| Agent Activity Log | When execute+learn nodes ship |
| Settings / Integrations | When Search Console OAuth ships |
| Approval Queue | When human-in-the-loop ships |

---

## Screen Specifications

### Screen 1: Dashboard

**Purpose:** Answer "How are my sites doing?" and "What did the agent find?"

**URL:** `/`

```
┌─────────────────────────────────────────────────────────┐
│  SSA                                    [+ Add Site]    │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │  AGENT STATUS                                    │    │
│  │  ● Last run: 2h ago  │  Next run: in 22h        │    │
│  │  Status: Completed — found 12 issues             │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
│  YOUR SITES                                              │
│  ┌────────────────────┐  ┌────────────────────┐        │
│  │  example.com       │  │  myblog.dev        │        │
│  │  ───────────────── │  │  ───────────────── │        │
│  │  Pages: 47         │  │  Pages: 23         │        │
│  │  Issues: 8 (2 crit)│  │  Issues: 4 (0 crit)│        │
│  │  Health: 72%       │  │  Health: 89%       │        │
│  │  Last crawl: 2h ago│  │  Last crawl: 2h ago│        │
│  │                    │  │                    │        │
│  │  [View Details →]  │  │  [View Details →]  │        │
│  └────────────────────┘  └────────────────────┘        │
│                                                          │
│  RECENT ISSUES (across all sites)                        │
│  ┌─────────────────────────────────────────────────┐    │
│  │  🔴 Missing meta description (5 pages)  example │    │
│  │  🟡 Slow response time (>3s)            example │    │
│  │  🟡 Thin content (<300 words)           myblog  │    │
│  │  🔵 Internal link opportunity           example │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

**Components:**
- `AgentStatusBanner` — Current agent state, last/next run
- `SiteCard` — Site summary with health score and issue count
- `IssuesList` — Severity-sorted list of recent issues

**Data requirements:**
- Sites with aggregated page count, issue count, health score
- Latest agent run status
- Recent issues across all sites (top 10)

---

### Screen 2: Site Detail

**Purpose:** Answer "What's happening with this specific site?" Deep dive into pages and issues.

**URL:** `/sites/[id]`

```
┌─────────────────────────────────────────────────────────┐
│  ← Back    example.com                  [Run Agent Now] │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │  HEALTH  │  │  PAGES   │  │  ISSUES  │             │
│  │   72%    │  │    47    │  │    8     │             │
│  │  ↓ from  │  │  crawled │  │  2 crit  │             │
│  │   78%    │  │          │  │  3 high  │             │
│  └──────────┘  └──────────┘  └──────────┘             │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │  TABS: [Issues] [Pages] [Agent Runs]            │    │
│  ├─────────────────────────────────────────────────┤    │
│  │                                                  │    │
│  │  ISSUES TAB (default):                          │    │
│  │  Filter: [All] [Critical] [High] [Medium] [Low] │    │
│  │                                                  │    │
│  │  🔴 CRITICAL                                    │    │
│  │  ┌────────────────────────────────────────┐     │    │
│  │  │ Missing meta description               │     │    │
│  │  │ 5 pages affected                       │     │    │
│  │  │ Recommendation: Add unique meta...     │     │    │
│  │  └────────────────────────────────────────┘     │    │
│  │  ┌────────────────────────────────────────┐     │    │
│  │  │ Broken internal links                  │     │    │
│  │  │ 3 links returning 404                  │     │    │
│  │  │ Recommendation: Fix or redirect...     │     │    │
│  │  └────────────────────────────────────────┘     │    │
│  │                                                  │    │
│  │  PAGES TAB:                                     │    │
│  │  ┌──────────────────────────────────────────┐   │    │
│  │  │ URL          │ Title    │ Status │ Issues │   │    │
│  │  │ /            │ Home     │ ✓      │ 1     │   │    │
│  │  │ /about       │ About Us │ ✓      │ 0     │   │    │
│  │  │ /blog/post-1 │ Post 1   │ ⚠      │ 2     │   │    │
│  │  └──────────────────────────────────────────┘   │    │
│  │                                                  │    │
│  │  AGENT RUNS TAB:                                │    │
│  │  ┌──────────────────────────────────────────┐   │    │
│  │  │ Run #12 │ Observe+Analyze │ ✓ │ 2m ago  │   │    │
│  │  │ Run #11 │ Observe+Analyze │ ✓ │ 26h ago │   │    │
│  │  │ Run #10 │ Observe         │ ✗ │ 50h ago │   │    │
│  │  └──────────────────────────────────────────┘   │    │
│  │                                                  │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

**Components:**
- `SiteHeader` — Domain, back button, manual trigger
- `StatCards` — Health %, page count, issue count
- `TabView` — Issues / Pages / Agent Runs
- `IssueCard` — Severity, title, affected pages, recommendation
- `PageTable` — Sortable table of all crawled pages
- `RunHistory` — Agent execution log

**Data requirements:**
- Site details with aggregated stats
- Issues filtered by severity, grouped by type
- Pages with crawl status and issue count
- Agent run history with duration and outcome

---

### Screen 3: Add Site (Onboarding)

**Purpose:** Get a new site into the system and trigger first crawl.

**URL:** `/sites/new`

```
┌─────────────────────────────────────────────────────────┐
│  ← Back         Add a Site                              │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Step 1 of 2: Enter your domain                         │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Domain: [https://example.com          ]        │    │
│  │                                                  │    │
│  │  Site name: [My Website                ]        │    │
│  │  (optional — we'll use the domain if blank)     │    │
│  │                                                  │    │
│  │               [Validate & Continue →]            │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
│  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─     │
│                                                          │
│  Step 2 of 2: First crawl                               │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │  ✓ Domain verified (200 OK)                     │    │
│  │  ✓ robots.txt found                             │    │
│  │  ✓ Sitemap found (47 URLs)                      │    │
│  │                                                  │    │
│  │  Crawl settings:                                │    │
│  │  Max pages: [100    ] (recommended for start)   │    │
│  │  Respect robots.txt: [✓]                        │    │
│  │                                                  │    │
│  │         [Start First Crawl →]                   │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
│  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─     │
│                                                          │
│  (After clicking "Start First Crawl"):                  │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │  🔄 Crawling example.com...                     │    │
│  │                                                  │    │
│  │  Pages found: 23/100                            │    │
│  │  ████████████░░░░░░░░░░░░░ 23%                  │    │
│  │                                                  │    │
│  │  Recent:                                        │    │
│  │  ✓ / (200, 1.2s)                               │    │
│  │  ✓ /about (200, 0.8s)                          │    │
│  │  ✓ /blog (200, 1.5s)                           │    │
│  │  ⚠ /old-page (301 → /new-page)                 │    │
│  │                                                  │    │
│  │  [View Site Dashboard →] (appears when done)    │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

**Flow:**
1. User enters domain → validation (is it reachable? has robots.txt? has sitemap?)
2. Show validation results → user confirms crawl settings
3. Start crawl → show real-time progress
4. When complete → redirect to Site Detail page

---

## User Workflows

### Workflow 1: First-Time Setup

```
User signs in (first time)
       │
       ▼
Dashboard (empty state: "Add your first site")
       │
       ▼
Add Site → Enter domain → Validate → Start crawl
       │
       ▼
Crawl progress (real-time updates via polling)
       │
       ▼
Redirect to Site Detail (issues already populated)
       │
       ▼
User reviews issues found by agent
```

### Workflow 2: Daily Check-in

```
User opens Dashboard
       │
       ▼
Sees agent status ("Ran 2h ago, found 3 new issues")
       │
       ▼
Clicks into site with most issues
       │
       ▼
Reviews new issues sorted by severity
       │
       ▼
(Future: approves agent's recommended fixes)
```

### Workflow 3: Manual Agent Trigger

```
User made changes to their site
       │
       ▼
Opens Site Detail → clicks "Run Agent Now"
       │
       ▼
Agent runs observe+analyze cycle
       │
       ▼
New issues appear (or existing ones resolved)
```

---

## Interaction Patterns

### Loading States
- Skeleton loaders for cards and tables (no spinners)
- Optimistic UI for actions (mark issue dismissed → instant, revert on error)

### Empty States
- Dashboard with no sites: "Add your first site to get started" + prominent CTA
- Site with no issues: "No issues found — your site looks healthy 🎉"
- Site with no crawl yet: "Waiting for first crawl to complete..."

### Error States
- Crawl failed: Show last successful state + "Retry" button
- API error: Toast notification with retry action
- Domain unreachable: Clear message in onboarding with troubleshooting hints

### Notifications (Future)
- No real-time notifications in MVP
- Later: email digest when agent finds critical issues

---

## Responsive Design

### MVP: Desktop-First
- Primary target: 1280px+ (laptop/desktop)
- Tablet (768px): Stack cards vertically, maintain usability
- Mobile (375px): Functional but not optimized — this is a work tool, not a consumer app

### Layout Grid
- Max content width: 1200px
- 12-column grid
- Sidebar: none (top nav only in MVP)
- Content: centered with generous padding

---

## Component Library

Based on shadcn/ui. Key components needed for MVP:

| Component | Purpose |
|-----------|---------|
| `Card` | Site cards, issue cards, stat cards |
| `Table` | Page inventory, agent run history |
| `Badge` | Issue severity (critical/high/medium/low) |
| `Button` | Actions (add site, run agent, dismiss issue) |
| `Input` | Domain input, search/filter |
| `Tabs` | Site detail section switching |
| `Progress` | Crawl progress bar |
| `Alert` | Agent status banner |
| `Skeleton` | Loading states |
| `Toast` | Success/error notifications |

---

## Design Tokens

```css
/* Colors - semantic */
--color-critical: #ef4444;  /* red-500 */
--color-high: #f97316;      /* orange-500 */
--color-medium: #eab308;    /* yellow-500 */
--color-low: #3b82f6;       /* blue-500 */
--color-success: #22c55e;   /* green-500 */

/* Health score gradient */
--health-good: #22c55e;     /* 80-100% */
--health-warning: #eab308;  /* 50-79% */
--health-poor: #ef4444;     /* 0-49% */

/* Spacing scale (Tailwind default) */
/* 4px base: 1=4px, 2=8px, 3=12px, 4=16px, 6=24px, 8=32px */
```

---

## Navigation

### MVP: Minimal Top Nav

```
┌─────────────────────────────────────────────────┐
│  [Logo] SSA          [+ Add Site]    [Profile] │
└─────────────────────────────────────────────────┘
```

- Logo/SSA → Dashboard
- Add Site → Onboarding flow
- Profile → Sign out (single user, no settings needed yet)

### Future: Add sidebar when screens exceed 4

---

## Health Score Calculation

Simple weighted formula for MVP:

```
Health = 100 - (critical_issues × 15) - (high_issues × 8) - (medium_issues × 3) - (low_issues × 1)
Minimum: 0, Maximum: 100
```

Displayed as a percentage with color coding (good/warning/poor).
