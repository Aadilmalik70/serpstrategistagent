---
description: Apply only the plugin's narrow safe-fix catalog and verify after each change.
allowed-tools: ["*"]
---

Use the `seo-safe-fixes` and `seo-wordpress-fix-routing` skills during this workflow.

Allowed safe-fix catalog:

- narrow metadata fixes on a single page/post/template
- scoped canonical fixes when the intended canonical target is unambiguous
- existing-pattern schema additions
- scoped internal link improvements on a small number of pages

Rules:

1. Make one narrow fix slice at a time.
2. Immediately run the narrowest validation available after the first substantive change.
3. If the change grows beyond one clear slice, stop and convert it into a proposal.
4. For WordPress, do not perform broad rewrites or publishing actions in this workflow.

Return:

1. what was fixed
2. what was validated
3. what still needs approval

Never claim a fix is complete without naming the validation that was run.