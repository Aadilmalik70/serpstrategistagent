# Phase 9 — Crawl frontier retry and quality telemetry

This slice hardens the durable first-party crawler after a crawl has already
stored useful pages. It adds an explicit operator retry for failed or blocked
frontier URLs while preserving successful rows, and exposes a compact quality
summary through the crawl-status API.

## Behavior

- `POST /crawl/{job_id}/retry-failed` is owner/admin-only.
- The job must be terminal and have at least one `failed` or `blocked` frontier
  row.
- Only those rows are reset to `queued`; completed rows remain completed.
- A retry starts from the persisted frontier and gets a fresh retry budget.
- The existing cancellation/resume flow remains the safe pause/checkpoint path.
- The status response includes `frontier`, `retryable_failed_pages`, and
  `quality` metrics for UI and operational diagnostics.

## Verification

1. Run a crawl against a site with at least one reachable page and one
   temporarily failing or bot-blocked URL.
2. Confirm the completed pages remain in the page inventory.
3. Click **Retry N failed pages** in the site header.
4. Confirm the crawl status returns to `queued`, then `running`.
5. Confirm the previously completed frontier rows are not fetched again and the
   failed/blocked rows are attempted.
6. Confirm the API status includes success, failure, blocked, and deferred
   counts under `quality`/`frontier`.

## Safety boundary

The retry action does not bypass robots handling, public-target validation,
rate limiting, WAF detection, renderer limits, workspace authorization, or
monthly crawl quota enforcement.
