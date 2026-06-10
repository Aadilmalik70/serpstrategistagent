---
description: Run a bounded SEO audit using packaged MCP servers and local repo or WordPress evidence.
allowed-tools: ["*"]
---

Use the `seo-audit-loop` and `seo-issue-triage` skills during this workflow.

Audit order:

1. Confirm target site and current-site scope
2. Pull recent Search Console evidence
3. Pull GA4 evidence through the official server
4. Pull SERP context through SerpAPI
5. Inspect local repo or WordPress surface
6. Classify issues into safe-fix, approval-needed, and report-only

Default to 28-60 day windows unless the user explicitly requests historical analysis.

Required output sections:

1. Scope confirmed
2. Evidence summary
3. Top issues
4. Safe fixes now
5. Approval-needed changes
6. Risks and unknowns

When Search Console surfaces old URLs, label them as historical unless current-site evidence proves they are still live and relevant.