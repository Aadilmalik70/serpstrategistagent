---
name: seo-mcp-diagnostics
description: Use when packaged MCP servers fail to launch, authenticate, or return expected data.
allowed-tools: ["view", "powershell", "bash", "web_fetch"]
---

Separate server failure, auth failure, API enablement failure, and permission-state failure.

Use the packaged scripts before doing manual diagnosis whenever possible.

Order remediation from cheapest to most specific. Avoid generic setup advice when a single missing variable, missing account, or missing credential file explains the failure.