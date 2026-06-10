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

Escalation rules:

- `safe-fix` only when the change is narrow and the intended state is unambiguous
- `approval-needed` when user intent, scope, or business impact is broader
- `report-only` when evidence is weak, conflicting, or historical only

Severity guide:

- high: indexation, canonical, tracking, or sitewide technical issues
- medium: page-level ranking blockers or conversion-impacting issues
- low: polish or incremental snippet improvements