# Phase 5 Slice 2 — URL Inspection and Indexation Opportunities

This slice adds a quota-bounded Search Console URL Inspection pipeline. It stores
the latest indexed result per URL, reconciles indexation findings, and creates
simulation-only governed draft actions.

## Production rollout

1. Deploy the application with `URL_INSPECTION_WORKER_ENABLED=false`.
2. Run `alembic upgrade head` and confirm migration `020` completed.
3. Enable `URL_INSPECTION_WORKER_ENABLED=true` on exactly one worker service.
4. Keep the API replicas disabled for this worker unless that service is the
   single intended worker.
5. Confirm `/health` reports API `0.15.0` and `url_inspection_worker: enabled` on
   the worker service.

Optional bounds:

- `URL_INSPECTION_MAX_URLS_PER_JOB=50`
- `URL_INSPECTION_MIN_INTERVAL_MINUTES=1440`
- `URL_INSPECTION_WORKER_BATCH_SIZE=1`
- `URL_INSPECTION_JOB_MAX_ATTEMPTS=4`
- `URL_INSPECTION_RETRY_BASE_SECONDS=60`

The configured Google connection must include Search Console read access, and
its selected property must cover the site. URL Inspection reports Google's
indexed version; it does not perform the Search Console live URL test.

## UI verification

1. Sign in and open a site with a configured Search Console property.
2. Open the Search Performance panel.
3. Select **Inspect indexation**.
4. Confirm the control changes to a queued/running state and remains pollable
   across a page refresh.
5. Confirm completion reports inspected URL and opportunity counts.
6. Confirm **Latest URL Inspection evidence** shows real URL, verdict, coverage,
   robots, indexing, fetch, and canonical evidence returned by Google.
7. Confirm active `not indexed`, `indexation blocked`, or `canonical mismatch`
   findings appear in the opportunity list.
8. Open Operator Actions and confirm corresponding actions are drafts with the
   `simulation` adapter. Do not approve a real mutation for this verification.
9. Select **Inspect indexation** again inside the cooldown window and confirm the
   completed job is reused instead of consuming quota again.

## Failure verification

- A URL outside the selected site returns `422` and is never sent to Google.
- A mismatched Search Console property returns `409`.
- Provider `429` and `5xx` responses retry with a durable backoff.
- Worker restarts resume from the last persisted URL checkpoint.
- Expired leases are recovered without creating a second active site job.
- Search Analytics opportunity reconciliation does not resolve active URL
  Inspection opportunities.

## Rollback

Disable `URL_INSPECTION_WORKER_ENABLED` first. If migration `020` must be rolled
back, active URL Inspection jobs are marked failed before the result and attempt
tables and active-job index are removed.
