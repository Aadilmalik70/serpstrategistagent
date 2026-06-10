---
name: seo-wordpress-fix-routing
description: Use when a requested SEO fix targets WordPress and must be routed between safe edits and approval-required changes.
allowed-tools: ["*"]
---

Allow only scoped metadata or content adjustments in v1. Escalate anything broader.

Safe WordPress examples:

- title or meta description adjustment on one post/page
- scoped internal link insertion on one post/page
- small canonical correction where the target is unambiguous

Escalate:

- plugin changes
- theme/template edits
- bulk content rewrites
- auto-publishing

If the requested change touches multiple posts or pages, default to proposal mode.