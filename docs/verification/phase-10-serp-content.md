# Phase 10 — SERP Content

SERP Content turns existing search evidence into a governed creation workflow.
It is intentionally separate from Content Intelligence: Content Intelligence
diagnoses decay, gaps, entities, and links; SERP Content converts those signals
into briefs and reviewable drafts.

## Workflow

`Opportunity → Brief → Draft → Edit → Quality gates → Action Queue → Approval`

## API surface

- `GET /sites/{site_id}/content`
- `POST /sites/{site_id}/content/briefs`
- `POST /content/briefs/{brief_id}/generate`
- `PUT /content/drafts/{draft_id}`
- `POST /content/drafts/{draft_id}/quality-check`
- `POST /content/drafts/{draft_id}/submit-for-approval`

## Safety boundary

- Every endpoint is workspace-scoped.
- Brief and draft creation requires an editor, admin, or owner role.
- AI-assisted generation falls back to an evidence scaffold when the provider
  is unavailable; it does not invent evidence.
- Quality checks are deterministic and visible before approval.
- Submit-for-approval creates a `content_draft` governed action with a
  simulation target. It does not publish to a CMS or repository.
- Publishing remains behind the existing Action Queue approval and execution
  adapters.

## Manual verification

1. Apply migration `025`.
2. Open a crawled site and select `Create → SERP Content`.
3. Confirm opportunities are sourced from Content Intelligence, Search
   Console opportunities, and citation gaps when those records exist.
   Search Console URLs with performance evidence must be labeled as refreshes
   of existing pages, not new pages. Indexing/canonical diagnostics and
   privacy, terms, cookies, admin, and other system paths must not appear in
   this content-creation queue.
4. Create a brief and verify its outline, information-gain requirements,
   internal-link targets, and evidence are visible.
5. Generate an AI-assisted draft. If the gateway is unavailable, confirm the
   UI reports an evidence scaffold instead of showing a fake AI result.
6. Edit Markdown, save a new version, and verify the word count changes.
7. Run quality gates and resolve the visible failed checks.
8. Submit for approval and verify one `content_draft` action appears in the
   Action Queue with `execution_target.adapter=simulation`.
9. Confirm no CMS update, GitHub commit, or pull request is created by this
   module.
