# SEO Operator Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a repo-installable GitHub Copilot CLI plugin that packages `searchConsoleSuite`, `ga4Official`, and `serpapi`, plus guided SEO commands, skills, and safety hooks for GitHub repos and WordPress.

**Architecture:** The plugin lives in a dedicated `plugins/seo-operator/` directory and packages Copilot CLI primitives instead of a standalone app. MCP setup is split by transport type, with local stdio launchers for Search Console and GA4, remote HTTP for SerpAPI, and hooks enforcing a narrow safe-fix policy.

**Tech Stack:** GitHub Copilot CLI plugin format, Markdown-based commands/skills/agents, JSON manifest and MCP config, PowerShell and bash launcher scripts, Node `npx`, `uvx`, remote HTTP MCP.

---

## File Map

### New files to create

- `plugins/seo-operator/plugin.json`
- `plugins/seo-operator/.mcp.json`
- `plugins/seo-operator/hooks.json`
- `plugins/seo-operator/README.md`
- `plugins/seo-operator/agents/seo-operator.agent.md`
- `plugins/seo-operator/commands/seo-setup.md`
- `plugins/seo-operator/commands/seo-mcp-check.md`
- `plugins/seo-operator/commands/seo-audit.md`
- `plugins/seo-operator/commands/seo-recommend.md`
- `plugins/seo-operator/commands/seo-fix-safe.md`
- `plugins/seo-operator/commands/seo-inspect-url.md`
- `plugins/seo-operator/commands/seo-content-plan.md`
- `plugins/seo-operator/skills/seo-audit-loop/SKILL.md`
- `plugins/seo-operator/skills/seo-issue-triage/SKILL.md`
- `plugins/seo-operator/skills/seo-safe-fixes/SKILL.md`
- `plugins/seo-operator/skills/seo-wordpress-fix-routing/SKILL.md`
- `plugins/seo-operator/skills/seo-growth-opportunities/SKILL.md`
- `plugins/seo-operator/skills/seo-mcp-diagnostics/SKILL.md`
- `plugins/seo-operator/scripts/check-prereqs.ps1`
- `plugins/seo-operator/scripts/check-prereqs.sh`
- `plugins/seo-operator/scripts/start-search-console-mcp.ps1`
- `plugins/seo-operator/scripts/start-search-console-mcp.sh`
- `plugins/seo-operator/scripts/start-ga4-official-mcp.ps1`
- `plugins/seo-operator/scripts/start-ga4-official-mcp.sh`
- `plugins/seo-operator/scripts/pretool-policy.ps1`
- `plugins/seo-operator/scripts/pretool-policy.sh`
- `plugins/seo-operator/scripts/posttool-guidance.ps1`
- `plugins/seo-operator/scripts/posttool-guidance.sh`

### Existing files to reference only

- `docs/superpowers/specs/2026-06-10-seo-operator-plugin-design.md`
- `.vscode/mcp.json`
- `scripts/check-seo-mcp-prereqs.ps1`
- `scripts/start-search-console-mcp.ps1`
- `scripts/start-ga4-official-mcp.ps1`

## Task 1: Scaffold The Plugin Directory And Manifest

**Files:**
- Create: `plugins/seo-operator/plugin.json`
- Create: `plugins/seo-operator/README.md`

- [ ] **Step 1: Create the plugin directory structure**

Create these directories:

```text
plugins/seo-operator/
plugins/seo-operator/agents/
plugins/seo-operator/commands/
plugins/seo-operator/skills/seo-audit-loop/
plugins/seo-operator/skills/seo-issue-triage/
plugins/seo-operator/skills/seo-safe-fixes/
plugins/seo-operator/skills/seo-wordpress-fix-routing/
plugins/seo-operator/skills/seo-growth-opportunities/
plugins/seo-operator/skills/seo-mcp-diagnostics/
plugins/seo-operator/scripts/
```

- [ ] **Step 2: Write `plugin.json`**

Use this content:

```json
{
  "name": "seo-operator",
  "description": "Workflow-heavy GitHub Copilot CLI plugin for SEO setup, audit, recommendation, and safe fixes using Search Console, GA4, and SerpAPI.",
  "version": "0.1.0",
  "author": {
    "name": "SERP Strategist"
  },
  "license": "MIT",
  "keywords": ["seo", "search-console", "ga4", "serpapi", "wordpress", "copilot-plugin"],
  "agents": "agents/",
  "skills": "skills/",
  "commands": "commands/",
  "hooks": "hooks.json",
  "mcpServers": ".mcp.json"
}
```

- [ ] **Step 3: Write the plugin README**

Start with this content:

```md
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

## Verify

```bash
copilot plugin list
copilot mcp list
```
```

- [ ] **Step 4: Verify manifest shape manually**

Check:

- file is valid JSON
- `name` is kebab-case
- `commands`, `skills`, `agents`, `hooks`, and `mcpServers` point to the intended paths

- [ ] **Step 5: Commit**

Run:

```bash
git add plugins/seo-operator/plugin.json plugins/seo-operator/README.md
git commit -m "feat: scaffold seo operator copilot plugin"
```

Expected: a commit containing the manifest and README scaffold.

## Task 2: Package MCP Servers For The Plugin

**Files:**
- Create: `plugins/seo-operator/.mcp.json`
- Create: `plugins/seo-operator/scripts/start-search-console-mcp.ps1`
- Create: `plugins/seo-operator/scripts/start-search-console-mcp.sh`
- Create: `plugins/seo-operator/scripts/start-ga4-official-mcp.ps1`
- Create: `plugins/seo-operator/scripts/start-ga4-official-mcp.sh`
- Create: `plugins/seo-operator/scripts/check-prereqs.ps1`
- Create: `plugins/seo-operator/scripts/check-prereqs.sh`

- [ ] **Step 1: Write the Windows Search Console launcher**

Use this content in `plugins/seo-operator/scripts/start-search-console-mcp.ps1`:

```powershell
$ErrorActionPreference = "Stop"

$npx = (Get-Command npx -ErrorAction Stop).Source
& $npx "-y" "search-console-mcp"
```

- [ ] **Step 2: Write the Unix Search Console launcher**

Use this content in `plugins/seo-operator/scripts/start-search-console-mcp.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

exec npx -y search-console-mcp
```

- [ ] **Step 3: Write the Windows GA4 launcher**

Use this content in `plugins/seo-operator/scripts/start-ga4-official-mcp.ps1`:

```powershell
$ErrorActionPreference = "Stop"

$uvx = (Get-Command uvx -ErrorAction Stop).Source
& $uvx "--from" "analytics-mcp" "analytics-mcp"
```

- [ ] **Step 4: Write the Unix GA4 launcher**

Use this content in `plugins/seo-operator/scripts/start-ga4-official-mcp.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

exec uvx --from analytics-mcp analytics-mcp
```

- [ ] **Step 5: Write prerequisite check scripts**

Use this PowerShell content:

```powershell
$ErrorActionPreference = "Stop"

$checks = @(
    @{ Name = "Node npx"; Command = "npx" },
    @{ Name = "uvx"; Command = "uvx" },
    @{ Name = "Copilot CLI"; Command = "copilot" }
)

foreach ($check in $checks) {
    $cmd = Get-Command $check.Command -ErrorAction SilentlyContinue
    if ($null -eq $cmd) {
        Write-Host "[missing] $($check.Name)" -ForegroundColor Red
    }
    else {
        Write-Host "[ok] $($check.Name): $($cmd.Source)" -ForegroundColor Green
    }
}
```

Use this bash content:

```bash
#!/usr/bin/env bash
set -euo pipefail

for cmd in npx uvx copilot; do
  if command -v "$cmd" >/dev/null 2>&1; then
    echo "[ok] $cmd: $(command -v "$cmd")"
  else
    echo "[missing] $cmd"
  fi
done
```

- [ ] **Step 6: Write `.mcp.json`**

Use this content:

```json
{
  "mcpServers": {
    "searchConsoleSuite": {
      "type": "stdio",
      "powershell": "${PLUGIN_ROOT}/scripts/start-search-console-mcp.ps1",
      "bash": "${PLUGIN_ROOT}/scripts/start-search-console-mcp.sh",
      "tools": ["*"],
      "timeout": 120000
    },
    "ga4Official": {
      "type": "stdio",
      "powershell": "${PLUGIN_ROOT}/scripts/start-ga4-official-mcp.ps1",
      "bash": "${PLUGIN_ROOT}/scripts/start-ga4-official-mcp.sh",
      "tools": ["*"],
      "env": {
        "GOOGLE_APPLICATION_CREDENTIALS": "${GOOGLE_APPLICATION_CREDENTIALS:-}",
        "GOOGLE_PROJECT_ID": "${GOOGLE_PROJECT_ID:-}",
        "GOOGLE_CLOUD_PROJECT": "${GOOGLE_CLOUD_PROJECT:-}"
      },
      "timeout": 120000
    },
    "serpapi": {
      "type": "http",
      "url": "https://mcp.serpapi.com/mcp",
      "tools": ["*"],
      "headers": {
        "Authorization": "Bearer ${SERPAPI_API_KEY:-}"
      },
      "timeout": 120000
    }
  }
}
```

- [ ] **Step 7: Verify scripts locally**

Run on Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File plugins/seo-operator/scripts/check-prereqs.ps1
```

Expected: `[ok]` or `[missing]` lines for `npx`, `uvx`, and `copilot`.

- [ ] **Step 8: Validate MCP config with Copilot CLI**

Run:

```bash
copilot plugin install ./plugins/seo-operator
copilot plugin list
copilot mcp list
```

Expected:

- plugin appears in installed plugin list
- MCP server names appear in the MCP listing

- [ ] **Step 9: Commit**

Run:

```bash
git add plugins/seo-operator/.mcp.json plugins/seo-operator/scripts/
git commit -m "feat: package seo operator mcp servers"
```

## Task 3: Add The Top-Level SEO Operator Agent

**Files:**
- Create: `plugins/seo-operator/agents/seo-operator.agent.md`

- [ ] **Step 1: Write the agent file**

Use this content:

```md
---
name: SEO Operator
description: Route SEO setup, audit, recommendation, and safe-fix tasks across the packaged MCP servers and plugin skills.
tools: ["*"]
infer: true
---

You are the SEO Operator for the SERP Strategist plugin.

Rules:

- Prefer plugin commands and skills over freeform wandering.
- Gather evidence before recommending or fixing.
- Treat Search Console windows longer than 60 days as historical unless the user explicitly asks for historical analysis.
- Use `ga4Official` as the primary GA4 integration path.
- Never broaden into high-risk edits when a narrow safe fix exists.
- Respect hook-enforced safety boundaries.
```

- [ ] **Step 2: Verify the agent loads**

Run:

```bash
copilot plugin install ./plugins/seo-operator
copilot
```

Then in interactive mode run:

```text
/agent
```

Expected: `SEO Operator` appears in the available agent list.

- [ ] **Step 3: Commit**

Run:

```bash
git add plugins/seo-operator/agents/seo-operator.agent.md
git commit -m "feat: add seo operator plugin agent"
```

## Task 4: Add Guided Operator Commands

**Files:**
- Create: `plugins/seo-operator/commands/seo-setup.md`
- Create: `plugins/seo-operator/commands/seo-mcp-check.md`
- Create: `plugins/seo-operator/commands/seo-audit.md`
- Create: `plugins/seo-operator/commands/seo-recommend.md`
- Create: `plugins/seo-operator/commands/seo-fix-safe.md`
- Create: `plugins/seo-operator/commands/seo-inspect-url.md`
- Create: `plugins/seo-operator/commands/seo-content-plan.md`

- [ ] **Step 1: Write `seo-setup.md`**

Use this content:

```md
---
description: Validate prerequisites, explain required credentials, and verify packaged MCP readiness for the SEO Operator plugin.
allowed-tools: ["view", "powershell", "bash", "web_fetch"]
---

Run the plugin prerequisite checks first, then inspect MCP readiness.

Requirements to validate:

- `npx` available
- `uvx` available
- `copilot` available
- Search Console auth path understood
- GA4 credentials present and APIs enabled
- `SERPAPI_API_KEY` configured for HTTP MCP auth

Return a concise readiness report with:

1. Ready
2. Blocked
3. Next steps
```

- [ ] **Step 2: Write `seo-mcp-check.md`**

Use this content:

```md
---
description: Re-check connectivity and authentication for the SEO Operator plugin MCP servers.
allowed-tools: ["view", "powershell", "bash", "web_fetch"]
---

Check each packaged MCP server and separate:

- server launch failure
- auth failure
- API/configuration failure

Summarize by server name and include the most probable fix.
```

- [ ] **Step 3: Write `seo-audit.md`**

Use this content:

```md
---
description: Run a bounded SEO audit using packaged MCP servers and local repo or WordPress evidence.
allowed-tools: ["*" ]
---

Audit order:

1. Confirm target site and current-site scope
2. Pull recent Search Console evidence
3. Pull GA4 evidence through the official server
4. Pull SERP context through SerpAPI
5. Inspect local repo or WordPress surface
6. Classify issues into safe-fix, approval-needed, and report-only

Default to 28-60 day windows unless the user explicitly requests historical analysis.
```

- [ ] **Step 4: Write `seo-recommend.md`, `seo-fix-safe.md`, `seo-inspect-url.md`, and `seo-content-plan.md`**

Use these short bodies:

```md
---
description: Turn audit evidence into a narrow prioritized SEO action plan.
allowed-tools: ["*"]
---

Use recent evidence and avoid recommendations based on legacy URLs unless explicitly labeled historical.
```

```md
---
description: Apply only the plugin's narrow safe-fix catalog and verify after each change.
allowed-tools: ["*"]
---

Only proceed with scoped low-risk changes. Stop and downgrade to a proposal if the change broadens beyond the safe-fix catalog.
```

```md
---
description: Deeply inspect one URL using Search Console, SERP, and local surface evidence.
allowed-tools: ["*"]
---

Return indexability, likely issue class, supporting evidence, and recommended next action.
```

```md
---
description: Generate content refresh and new-content opportunities without auto-publishing.
allowed-tools: ["*"]
---

Focus on current-site opportunities, not stale historical URLs.
```

- [ ] **Step 5: Reload and list commands**

Run:

```bash
copilot plugin install ./plugins/seo-operator
copilot
```

Then run:

```text
/help
```

Expected: command names are available for invocation.

- [ ] **Step 6: Commit**

Run:

```bash
git add plugins/seo-operator/commands/
git commit -m "feat: add seo operator guided commands"
```

## Task 5: Add Focused Skills For Audit, Triage, And Safe Fixes

**Files:**
- Create: `plugins/seo-operator/skills/seo-audit-loop/SKILL.md`
- Create: `plugins/seo-operator/skills/seo-issue-triage/SKILL.md`
- Create: `plugins/seo-operator/skills/seo-safe-fixes/SKILL.md`
- Create: `plugins/seo-operator/skills/seo-wordpress-fix-routing/SKILL.md`
- Create: `plugins/seo-operator/skills/seo-growth-opportunities/SKILL.md`
- Create: `plugins/seo-operator/skills/seo-mcp-diagnostics/SKILL.md`

- [ ] **Step 1: Write `seo-audit-loop/SKILL.md`**

Use this content:

```md
---
name: seo-audit-loop
description: Use when auditing a site with the SEO Operator plugin, before recommending or fixing issues.
allowed-tools: ["*"]
---

Gather evidence in this order:

1. Confirm target site and current-scope URLs
2. Pull recent Search Console evidence
3. Pull official GA4 evidence
4. Pull SerpAPI context
5. Check repo or WordPress surface
6. Classify issues

Do not recommend or fix before enough evidence exists.
```

- [ ] **Step 2: Write `seo-issue-triage/SKILL.md`**

Use this content:

```md
---
name: seo-issue-triage
description: Use when normalizing SEO findings into severity, confidence, evidence, and fixability.
allowed-tools: ["*"]
---

Every issue must be labeled:

- severity
- confidence
- evidence source
- safe-fix, approval-needed, or report-only
```

- [ ] **Step 3: Write `seo-safe-fixes/SKILL.md`**

Use this content:

```md
---
name: seo-safe-fixes
description: Use when applying low-risk SEO fixes in code-managed or WordPress-backed surfaces.
allowed-tools: ["*"]
---

Allowed safe fixes:

- narrow metadata fixes
- scoped canonical fixes
- existing-pattern schema additions
- scoped internal link improvements

After the first substantive edit, immediately run the narrowest verification available.
```

- [ ] **Step 4: Write the remaining skills**

Use these contents:

```md
---
name: seo-wordpress-fix-routing
description: Use when a requested SEO fix targets WordPress and must be routed between safe edits and approval-required changes.
allowed-tools: ["*"]
---

Allow only scoped metadata or content adjustments in v1. Escalate anything broader.
```

```md
---
name: seo-growth-opportunities
description: Use when finding quick wins, striking-distance terms, low-CTR pages, or refresh opportunities for the current site.
allowed-tools: ["*"]
---

Prefer 28-60 day windows. Treat older windows as historical analysis, not direct action guidance.
```

```md
---
name: seo-mcp-diagnostics
description: Use when packaged MCP servers fail to launch, authenticate, or return expected data.
allowed-tools: ["view", "powershell", "bash", "web_fetch"]
---

Separate server failure, auth failure, API enablement failure, and permission-state failure.
```

- [ ] **Step 5: List skills in Copilot CLI**

Run:

```bash
copilot plugin install ./plugins/seo-operator
copilot
```

Then run:

```text
/skills list
```

Expected: all six `seo-*` skills appear.

- [ ] **Step 6: Commit**

Run:

```bash
git add plugins/seo-operator/skills/
git commit -m "feat: add seo operator skills"
```

## Task 6: Enforce Safety With Hooks

**Files:**
- Create: `plugins/seo-operator/hooks.json`
- Create: `plugins/seo-operator/scripts/pretool-policy.ps1`
- Create: `plugins/seo-operator/scripts/pretool-policy.sh`
- Create: `plugins/seo-operator/scripts/posttool-guidance.ps1`
- Create: `plugins/seo-operator/scripts/posttool-guidance.sh`

- [ ] **Step 1: Write `pretool-policy` scripts**

Use this PowerShell content:

```powershell
$inputJson = [Console]::In.ReadToEnd() | ConvertFrom-Json
$toolName = $inputJson.toolName

$denyTools = @("powershell")
$dangerousPatterns = @("git push", "Remove-Item", "rm -rf")

if ($toolName -eq "powershell") {
    $toolArgs = ($inputJson.toolArgs | ConvertTo-Json -Compress)
    foreach ($pattern in $dangerousPatterns) {
        if ($toolArgs -like "*$pattern*") {
            @{ permissionDecision = "deny"; permissionDecisionReason = "Denied by SEO Operator safe-fix policy." } | ConvertTo-Json -Compress
            exit 0
        }
    }
}

@{} | ConvertTo-Json -Compress
```

Use this bash content:

```bash
#!/usr/bin/env bash
set -euo pipefail

payload="$(cat)"

if printf '%s' "$payload" | grep -E 'git push|rm -rf|Remove-Item' >/dev/null 2>&1; then
  printf '%s' '{"permissionDecision":"deny","permissionDecisionReason":"Denied by SEO Operator safe-fix policy."}'
else
  printf '%s' '{}'
fi
```

- [ ] **Step 2: Write `posttool-guidance` scripts**

Use this PowerShell content:

```powershell
@{ additionalContext = "If a substantive write just occurred, run the narrowest verification step now before widening scope." } | ConvertTo-Json -Compress
```

Use this bash content:

```bash
#!/usr/bin/env bash
set -euo pipefail

printf '%s' '{"additionalContext":"If a substantive write just occurred, run the narrowest verification step now before widening scope."}'
```

- [ ] **Step 3: Write `hooks.json`**

Use this content:

```json
{
  "version": 1,
  "hooks": {
    "preToolUse": [
      {
        "type": "command",
        "powershell": "${PLUGIN_ROOT}/scripts/pretool-policy.ps1",
        "bash": "${PLUGIN_ROOT}/scripts/pretool-policy.sh",
        "timeoutSec": 10
      }
    ],
    "postToolUse": [
      {
        "type": "command",
        "powershell": "${PLUGIN_ROOT}/scripts/posttool-guidance.ps1",
        "bash": "${PLUGIN_ROOT}/scripts/posttool-guidance.sh",
        "timeoutSec": 10
      }
    ]
  }
}
```

- [ ] **Step 4: Test hook blocking behavior**

Run:

```bash
copilot plugin install ./plugins/seo-operator
copilot
```

Then ask the agent to run a clearly blocked command like `git push`.

Expected: the request is denied with the hook reason.

- [ ] **Step 5: Commit**

Run:

```bash
git add plugins/seo-operator/hooks.json plugins/seo-operator/scripts/pretool-policy.* plugins/seo-operator/scripts/posttool-guidance.*
git commit -m "feat: add seo operator safety hooks"
```

## Task 7: Wire Documentation And Usage Guidance

**Files:**
- Modify: `plugins/seo-operator/README.md`

- [ ] **Step 1: Expand the README with first-run instructions**

Add sections covering:

```md
## First Run

1. Install the plugin
2. Run `seo-setup`
3. Authenticate Search Console
4. Configure GA4 credentials and enable required APIs
5. Set `SERPAPI_API_KEY`
6. Run `seo-mcp-check`

## Commands

- `seo-setup`
- `seo-mcp-check`
- `seo-audit`
- `seo-recommend`
- `seo-fix-safe`
- `seo-inspect-url`
- `seo-content-plan`

## Safety Model

The plugin auto-applies only narrow low-risk fixes and escalates broader changes.
```

- [ ] **Step 2: Add direct install examples**

Add examples for:

```bash
copilot plugin install OWNER/REPO:plugins/seo-operator
copilot plugin install ./plugins/seo-operator
copilot plugin update seo-operator
```

- [ ] **Step 3: Review the README for drift against the spec**

Check that the README does not mention:

- Supabase in v1
- LibreCrawl as directly bundled MCP in v1
- fully autonomous publishing

- [ ] **Step 4: Commit**

Run:

```bash
git add plugins/seo-operator/README.md
git commit -m "docs: document seo operator plugin usage"
```

## Task 8: End-To-End Plugin Validation

**Files:**
- Modify: `plugins/seo-operator/README.md` if validation uncovers setup gaps

- [ ] **Step 1: Reinstall the plugin from local path**

Run:

```bash
copilot plugin install ./plugins/seo-operator
copilot plugin list
```

Expected: `seo-operator` appears in the installed plugin list.

- [ ] **Step 2: Confirm packaged components load**

Run interactively:

```text
/agent
/skills list
/mcp show
```

Expected:

- `SEO Operator` listed
- all `seo-*` skills listed
- `searchConsoleSuite`, `ga4Official`, and `serpapi` visible

- [ ] **Step 3: Validate MCP diagnostics workflow**

Run the plugin command:

```text
/seo-mcp-check
```

Expected:

- reports missing auth or ready state per server
- distinguishes auth/configuration problems from server launch problems

- [ ] **Step 4: Validate the audit workflow in dry-run style**

Run:

```text
/seo-audit sc-domain:serpstrategists.com
```

Expected:

- workflow uses recent-window framing
- avoids claiming LibreCrawl is packaged directly
- classifies findings by safe-fix, approval-needed, and report-only

- [ ] **Step 5: Record any validation-driven fixes**

If validation finds issues, patch only the relevant plugin files and rerun the narrow validation that failed before moving on.

- [ ] **Step 6: Commit**

Run:

```bash
git add plugins/seo-operator/
git commit -m "test: validate seo operator plugin end to end"
```

## Spec Coverage Check

- Repo-installable Copilot CLI plugin: covered by Tasks 1, 2, 7, and 8.
- MCP packaging for `searchConsoleSuite`, `ga4Official`, and `serpapi`: covered by Task 2.
- Guided command surface: covered by Task 4.
- Focused workflow skills: covered by Task 5.
- Safety hooks and approval boundaries: covered by Task 6.
- GitHub repo and WordPress-safe operating model: covered by Tasks 4, 5, and 6.
- No Supabase in v1: preserved in Tasks 4 and 7.
- LibreCrawl deferred from direct MCP packaging: preserved in Tasks 2 and 7.

## Self-Review Notes

- No placeholder steps remain.
- Every task lists exact file paths and concrete commands.
- The plan stays within the approved v1 boundaries and does not reintroduce Supabase or direct LibreCrawl MCP packaging.
