---
description: Validate prerequisites, explain required credentials, and verify packaged MCP readiness for the SEO Operator plugin.
allowed-tools: ["view", "powershell", "bash", "web_fetch"]
---

Run the plugin prerequisite checks first, then inspect MCP readiness using the plugin scripts before suggesting manual steps.

Requirements to validate:

- `npx` available
- `uvx` available
- `copilot` available
- Search Console auth path understood
- GA4 credentials present and APIs enabled
- `SERPAPI_API_KEY` configured for HTTP MCP auth

Execution order:

1. Run `plugins/seo-operator/scripts/check-prereqs.ps1` on Windows or `check-prereqs.sh` on Unix.
2. Run `plugins/seo-operator/scripts/mcp-check.ps1` on Windows or `mcp-check.sh` on Unix.
3. Read the output before proposing any next action.
4. Only if a check is inconclusive, fall back to manual inspection.

Return a concise readiness report with:

1. Ready
2. Blocked
3. Next steps

If blocked, provide the smallest next action per integration instead of a generic setup dump.