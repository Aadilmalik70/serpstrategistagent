# SEO Operator Plugin

Repo-installable GitHub Copilot CLI plugin for SEO operations.

## What it includes

- Search Console MCP integration
- Official GA4 MCP integration
- SerpAPI MCP integration
- Guided commands for setup, audit, recommendation, and safe fixes
- Hooks for safety and approval boundaries

## Install

```bash
copilot plugin install OWNER/REPO:plugins/seo-operator
```

For local development on Windows, prefer an absolute path:

```powershell
copilot plugin install "C:/Users/DELL 2/Desktop/Projects/serpstrategistagent/plugins/seo-operator"
```

## Verify

```bash
copilot plugin list
copilot mcp list
```

## First Run

1. Install the plugin.
2. Run `seo-setup`.
3. Authenticate Search Console.
4. Configure GA4 credentials and enable the required Google APIs.
5. Set `SERPAPI_API_KEY`.
6. Run `seo-mcp-check`.

## Required Environment

- `GOOGLE_APPLICATION_CREDENTIALS`
- `GOOGLE_PROJECT_ID`
- `GOOGLE_CLOUD_PROJECT`
- `SERPAPI_API_KEY`

Recommended GA4 setup:

- enable Google Analytics Admin API
- enable Google Analytics Data API
- ensure the credential has property access

## Commands

- `seo-setup`
- `seo-mcp-check`
- `seo-audit`
- `seo-recommend`
- `seo-fix-safe`
- `seo-inspect-url`
- `seo-content-plan`

These commands are intended to behave as workflows, not one-line prompt aliases. They should run checks first, gather evidence second, and only then recommend or fix.

## Safety Model

The plugin auto-applies only narrow low-risk fixes and escalates broader changes.

Allowed by default in v1:

- scoped metadata fixes
- narrow canonical fixes
- existing-pattern schema additions
- scoped internal link improvements

Escalated instead of auto-applied in v1:

- broad template or theme changes
- automatic publication of major content changes
- risky WordPress mutations
- destructive shell operations

## Scope Boundaries

Included in v1:

- `searchConsoleSuite`
- `ga4Official`
- `serpapi`
- GitHub repo workflows
- limited WordPress-safe workflows

Not included in v1:

- Supabase persistence
- direct LibreCrawl MCP bundling
- full autonomous publishing

## Diagnostics Scripts

The plugin includes local scripts for prerequisite and MCP diagnostics:

- `plugins/seo-operator/scripts/check-prereqs.ps1`
- `plugins/seo-operator/scripts/check-prereqs.sh`
- `plugins/seo-operator/scripts/mcp-check.ps1`
- `plugins/seo-operator/scripts/mcp-check.sh`

## Updating

```bash
copilot plugin update seo-operator
```