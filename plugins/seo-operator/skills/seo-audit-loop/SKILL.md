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

Additional rules:

- Default to 28-60 day windows.
- Label longer windows as historical.
- Distinguish legacy URLs from current-site URLs before prioritization.
- If two evidence sources disagree, call out the conflict instead of smoothing it over.