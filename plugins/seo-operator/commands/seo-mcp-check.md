---
description: Re-check connectivity and authentication for the SEO Operator plugin MCP servers.
allowed-tools: ["view", "powershell", "bash", "web_fetch"]
---

Run the packaged MCP diagnostic script first.

Check each packaged MCP server and separate:

- server launch failure
- auth failure
- API/configuration failure

Check order:

1. Run `plugins/seo-operator/scripts/mcp-check.ps1` on Windows or `mcp-check.sh` on Unix.
2. Parse the result by integration.
3. If Search Console has accounts, treat it as authenticated.
4. For GA4, require credentials path plus project env values before calling it ready.
5. For SerpAPI, require `SERPAPI_API_KEY` presence.

Summarize by server name and include the most probable fix.

Do not claim a server is ready unless the script output supports it.