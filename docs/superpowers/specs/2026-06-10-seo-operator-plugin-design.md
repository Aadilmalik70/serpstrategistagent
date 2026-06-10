# SEO Operator Copilot CLI Plugin Design

## Summary

Build a GitHub Copilot CLI plugin that packages the MCP setup, commands, skills, and safety hooks needed to operate SERP Strategist workflows through Copilot.

The plugin is a control plane for SEO work, not the full product runtime. It should support:

- GitHub repository analysis and safe code fixes
- WordPress issue finding and limited safe content or metadata fixes
- Google Search Console via `searchConsoleSuite`
- Google Analytics 4 via the official `ga4Official` server
- SerpAPI via HTTP MCP
- A workflow-heavy command surface with safety hooks

The plugin must avoid pretending to provide durable workflow memory or full autonomy in v1. It should focus on repeatable operator workflows with explicit boundaries.

## Goals

- Installable from a Git repository with `copilot plugin install OWNER/REPO[:PATH]`
- Reusable across projects without copying workspace MCP config manually
- Strong guided workflows for setup, audit, recommendation, and safe fixes
- Safe auto-apply for a narrow set of low-risk changes
- Clear approval gates for destructive or high-risk operations
- Clean packaging of MCP servers with minimal auth friction

## Non-Goals

- No Supabase-backed persistent workflow state in v1
- No scheduler, cron runner, or autonomous background loop in v1
- No broad CMS support beyond WordPress in v1
- No fully autonomous publishing of new content in v1
- No direct LibreCrawl MCP bundling in v1 without a dedicated adapter

## Product Shape

The plugin should be workflow-heavy rather than agent-heavy.

Why:

- Commands give reliable entry points for repeat usage
- Skills let Copilot reason within a bounded SEO workflow
- Hooks enforce approval boundaries more reliably than prompt text alone
- MCP provides the data and action surfaces
- A single giant SEO agent would be harder to test, route, and trust

## V1 Scope

### Included

- `searchConsoleSuite` as a local stdio MCP server
- `ga4Official` as a local stdio MCP server
- `serpapi` as an HTTP MCP server
- GitHub repo issue analysis and safe fix generation/application
- WordPress-safe actions limited to metadata and scoped content adjustments
- Plugin commands for setup, diagnostics, audit, recommendation, and safe fixing
- Safety hooks for tool approval and policy reinforcement
- Minimal plugin-local runtime data only when needed via `${COPILOT_PLUGIN_DATA}`

### Excluded

- Supabase persistence
- Multi-CMS support beyond WordPress
- LibreCrawl as a direct MCP server unless an adapter is added later
- Automatic publishing of major content changes
- Broad template or theme rewrites
- Full multi-site autonomous orchestration

## MCP Packaging Strategy

The plugin should use a mixed MCP topology.

### `searchConsoleSuite`

- Transport: local `stdio`
- Launch: plugin script
- Role: Search Console analytics, SEO opportunity tools, inspection, sitemap and indexing utilities
- Notes:
  - Keep GA4 in this suite available only as optional secondary capability
  - Do not rely on the suite as the primary GA4 integration path

### `ga4Official`

- Transport: local `stdio`
- Launch: plugin script
- Role: authoritative GA4 property discovery, reporting, and realtime analytics
- Requirements:
  - `Google Analytics Admin API` enabled
  - `Google Analytics Data API` enabled
  - ADC or credential file configured
- Notes:
  - Keep this separate from `searchConsoleSuite` to avoid auth ambiguity

### `serpapi`

- Transport: remote `http`
- Auth: HTTP header, not URL-embedded secret
- Role: external SERP evidence, ranking context, query landscape, SERP feature research
- Notes:
  - Prefer hosted remote configuration in v1
  - Avoid path-based API key usage in committed config

### `librecrawl`

- V1 decision: not bundled as MCP directly
- Role in v1: external dependency only, or deferred to v1.5
- Reason:
  - No clear official public MCP packaging surface from the researched sources
  - Better treated as a future adapter project than forced into plugin config prematurely

## Proposed Plugin Layout

```text
plugins/seo-operator/
  plugin.json
  .mcp.json
  hooks.json
  README.md
  agents/
    seo-operator.agent.md
  commands/
    seo-setup.md
    seo-mcp-check.md
    seo-audit.md
    seo-recommend.md
    seo-fix-safe.md
    seo-inspect-url.md
    seo-content-plan.md
  skills/
    seo-audit-loop/
      SKILL.md
    seo-issue-triage/
      SKILL.md
    seo-safe-fixes/
      SKILL.md
    seo-wordpress-fix-routing/
      SKILL.md
    seo-growth-opportunities/
      SKILL.md
    seo-mcp-diagnostics/
      SKILL.md
  scripts/
    check-prereqs.ps1
    check-prereqs.sh
    start-search-console-mcp.ps1
    start-search-console-mcp.sh
    start-ga4-official-mcp.ps1
    start-ga4-official-mcp.sh
```

## `plugin.json`

The manifest should include:

- `name`: kebab-case plugin identifier
- `description`: clear operator-focused description so users understand scope
- `version`
- `author`
- `license`
- `keywords`
- `agents`
- `skills`
- `commands`
- `hooks`
- `mcpServers`

The plugin should be designed for direct repo installation first, with marketplace compatibility later.

## `.mcp.json`

The plugin MCP config should define only the supported v1 servers:

- `searchConsoleSuite`
- `ga4Official`
- `serpapi`

The config should use `${PLUGIN_ROOT}` for launcher scripts and environment expansion for secrets.

Design rules:

- Keep server names short and stable
- Avoid secret values committed directly in JSON
- Use env vars or interactive setup to supply credentials
- Prefer plugin scripts over raw package-manager commands in the config for local servers

## Commands

### `seo-setup`

Purpose:

- Validate prerequisites
- Guide MCP auth/setup steps
- Confirm server readiness

Output:

- readiness summary per integration
- next actions for missing auth or missing APIs

### `seo-mcp-check`

Purpose:

- Re-validate current MCP connectivity
- Distinguish auth failure from server failure

Output:

- per-server status and probable remediation

### `seo-audit`

Purpose:

- Collect signals from GSC, GA4, SerpAPI, repo files, and WordPress where relevant
- Classify issues into technical, content, indexation, analytics, and opportunity buckets

Output:

- prioritized issue report
- grouped by safe-fix, approval-needed, and report-only

### `seo-recommend`

Purpose:

- Turn audit evidence into a narrow action plan
- Avoid mixing historical and current-site-only decisions without explicit date/URL bounds

Output:

- recommended actions with evidence and rationale

### `seo-fix-safe`

Purpose:

- Apply only the allowed safe-fix catalog
- Verify after each fix slice

Safe-fix examples:

- missing or poor meta titles/descriptions in code-managed pages
- obvious canonical mismatches in template/config code
- missing schema blocks where project pattern already exists
- internal linking adjustments on specific pages/posts
- robots or sitemap references when change scope is narrow

### `seo-inspect-url`

Purpose:

- Deep-dive one URL using Search Console, SERP signals, repo or WordPress evidence

Output:

- indexability, current likely issue class, recommended fix path

### `seo-content-plan`

Purpose:

- Propose content opportunities and content refresh candidates
- Avoid publishing automatically in v1

Output:

- content brief, target queries, existing-page refresh opportunities

## Skills

### `seo-audit-loop`

- Gather evidence in a fixed order
- Prevent premature fixes before enough signal exists

### `seo-issue-triage`

- Normalize findings into severity, confidence, evidence, and fixability

### `seo-safe-fixes`

- Define the allowed safe-fix catalog and verification expectations

### `seo-wordpress-fix-routing`

- Route WordPress-safe actions and deny broader CMS mutations by default

### `seo-growth-opportunities`

- Handle quick wins, striking distance, low CTR, and opportunity prioritization
- Prefer recent windows and current-site filtering over long historical windows

### `seo-mcp-diagnostics`

- Diagnose auth, setup, and connectivity failures across packaged MCP servers

## Agent

Use a single custom agent only if needed:

- `seo-operator.agent.md`

Purpose:

- Act as the top-level routing agent for SEO workflows
- Delegate to skills and built-in agents when appropriate

The custom agent should remain small. Most behavior should live in commands, skills, and hooks.

## Hooks Policy

The plugin should use `hooks.json` for real enforcement, not just prose guidance.

### `preToolUse`

Use to deny or gate:

- destructive shell commands
- broad write operations
- WordPress actions beyond the safe catalog
- repo-wide risky edits without explicit approval intent

### `postToolUse`

Use to append policy context after sensitive actions, for example:

- remind the model to verify the change
- mark the output as draft/proposed when risk threshold is exceeded

### `permissionRequest`

Use in CLI contexts to auto-allow narrow safe actions and deny known dangerous categories.

### `agentStop`

Use sparingly to force one more turn only when the workflow has not completed required validation.

## Approval Model

Default mode: `auto-apply safe fixes`

### Safe by default

Allowed without escalation when evidence is strong and scope is narrow:

- isolated metadata fixes
- small structured-data additions following existing patterns
- scoped internal link improvements
- narrow canonical/config fixes in code-controlled surfaces

### Approval required

- deleting or deindexing content broadly
- changing templates across many pages
- publishing new content automatically
- modifying authentication/configuration secrets
- major WordPress content rewrites
- large batches of edits without narrow verification

### Report only

- ambiguous content strategy decisions
- weakly supported technical diagnoses
- broad site architecture changes

## Data Gathering Order

To reduce mediocre output, the plugin should gather evidence in this order:

1. Current-site scope confirmation
2. Search Console visibility and issue signals
3. GA4 behavior and engagement signals
4. SerpAPI external SERP context
5. Local surface evidence from repo or WordPress
6. Issue classification
7. Safe-fix or recommendation path

Important rule:

- Prefer 28-60 day windows by default for live decision-making
- Treat long historical windows as explicitly historical analysis, not current-site action guidance

## WordPress Boundaries

Allowed in v1:

- metadata edits
- canonical corrections on specific items
- limited content updates on a scoped page/post
- internal link updates on a scoped page/post

Disallowed in v1 without approval:

- broad theme/template changes
- plugin installation or removal
- raw DB-level mutations
- autonomous publication of major new articles

## GitHub Repo Boundaries

Allowed in v1:

- narrow code/template/content fixes
- PR or patch generation
- safe direct edits when policy allows

Required behavior:

- validate immediately after each substantive edit
- keep fixes root-cause oriented and narrow

## Runtime State

V1 should not pretend to be a durable workflow engine.

Allowed runtime state:

- minimal plugin-local config or cache via `${COPILOT_PLUGIN_DATA}`
- recent setup status or site mapping only if needed

Not allowed in v1:

- long-term issue history as a product memory layer
- multi-user operational state
- cross-machine workflow persistence

## Risks

### High risk

- Plugin skills or agents being shadowed by project-level customizations
- GA4 auth/API readiness failures
- Enterprise allowlists blocking non-default MCP servers
- Overly broad safe-fix policy causing low-quality autonomous edits

### Medium risk

- SerpAPI secret leakage if configured poorly
- Historical Search Console data contaminating current recommendations
- Plugin cache causing confusion during development because reinstall is required
- Windows vs bash launcher drift if scripts diverge

### Deferred risk

- LibreCrawl adapter design and maintenance burden
- Missing persistence causing reduced resume quality across sessions

## Testing Strategy

### Packaging tests

- install plugin from local path
- reinstall after changes and verify updated components load
- install from repo spec

### MCP tests

- `searchConsoleSuite` auth and basic property listing
- `ga4Official` account summary and property report
- `serpapi` connectivity and authenticated request

### Workflow tests

- audit on a code-managed site
- audit on a WordPress-backed site
- safe-fix application on one narrow issue per surface
- approval-required issue correctly blocked or downgraded to proposal

### Safety tests

- destructive shell action denied by hook
- risky WordPress mutation denied or escalated
- post-fix verification step always runs after substantive edits

## Delivery Recommendation

Build v1 in two phases.

### Phase 1

- plugin manifest
- MCP packaging for `searchConsoleSuite`, `ga4Official`, `serpapi`
- prerequisite scripts
- `seo-setup`, `seo-mcp-check`, `seo-audit`, `seo-fix-safe`
- basic hooks

### Phase 2

- richer recommendation and content-planning commands
- stronger WordPress routing skill
- optional marketplace packaging
- LibreCrawl adapter exploration

## Open Questions Resolved In This Design

- Install mode: Git repository plugin first
- Workflow surface: both guided commands and one primary operator path
- Fix mode: auto-apply safe fixes only
- Write targets: GitHub repos and WordPress
- Persistence: no Supabase in v1

## Recommendation

Proceed with a workflow-heavy Copilot CLI plugin that packages three MCP servers in v1:

- `searchConsoleSuite`
- `ga4Official`
- `serpapi`

Treat LibreCrawl as a deferred adapter project rather than forcing it into the first release. This keeps the plugin installable, safer, and less brittle while still delivering the core operator workflows.