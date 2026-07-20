# Phase 6 Slice 3 — Technical Findings to exact GitHub patches

## Release boundary

- API: `0.18.0`
- Database migration: none; existing JSON action contracts store planning metadata
- Input: one active crawl-backed Technical Finding affecting one URL
- Output: either one exact, operator-reviewable GitHub full-file patch or an explicit simulation fallback
- Still human-controlled: approval, draft-PR review, merge, deployment and merged-PR revert

## Required configuration

The API or agent service that runs the Technical Finding pipeline requires:

```env
AI_GATEWAY_API_KEY=<server-managed-key>
GITHUB_APP_ID=<app-id>
GITHUB_APP_SLUG=<app-slug>
GITHUB_APP_PRIVATE_KEY_BASE64=<complete-private-key-pem-as-base64>
GITHUB_PATCH_PLANNING_ENABLED=true
```

Draft-PR execution remains a separate rollout:

```env
GITHUB_EXECUTION_ENABLED=true
EXECUTION_WORKER_ENABLED=true
```

Never place GitHub App or AI gateway secrets in the frontend service.

## Data boundary

Patch planning is opt-in because it sends one bounded mapped-repository source
file, the finding description, affected URL and bounded evidence to the
configured server-managed AI gateway. Installation tokens remain ephemeral and
are sent only to GitHub. They are never included in the AI prompt, action,
snapshot, database, log or browser response.

Default bounds:

- 3 planning attempts per Technical Finding refresh
- 5,000 repository tree entries
- 25 route/import source files inspected locally
- 64 KiB source candidate
- 200 added/deleted review lines
- one affected URL and one exact source file per action

## Source resolution

The first resolver supports conventional page sources for Next.js App Router,
Next.js Pages Router, HTML, Astro, Svelte, Vue and PHP. It maps `/` and static
routes such as `/about` to unambiguous `page`, route or `index` files. It rejects
ties instead of guessing. For image-alt findings, it follows bounded local
relative, `@/` and `~/` imports and requires exactly one source file to reproduce
the missing attribute. Only that selected file is sent to AI. Generated,
public-asset, dependency, build, API, test, hidden and protected paths are
excluded.

Supported bounded finding types include title/description metadata, H1,
canonical, viewport, homepage structured data and missing image alt text.
Redirects, orphan pages, thin-content rewrites, performance recommendations,
multi-page duplicate findings, dynamic routes and ambiguous source layouts stay
simulation-only until they receive their own evidence and validation contracts.

## Planner validation

The AI gateway must return strict JSON containing `can_patch`, complete
replacement `content`, a short `summary`, and `validation_notes`. The backend:

1. rejects empty or unchanged content;
2. enforces UTF-8 and configured byte/line limits;
3. applies finding-specific postconditions;
4. freezes the current Git blob SHA as `expected_sha`;
5. stores the exact full-file replacement before policy evaluation;
6. requires manual approval because the adapter is `github`.

For missing alt text, the source patch must reduce image tags that omit the
attribute and must not add an empty replacement. An explicit empty `alt=""` is a
valid decorative-image decision and the authoritative crawler does not report
it as missing. When meaningful alt text cannot be supported by the source
context, the planner must decline instead of inventing it.

## Deployment

1. Deploy API `0.18.0` with `GITHUB_PATCH_PLANNING_ENABLED=false`.
2. Confirm `/health` reports `github_patch_planning=disabled`.
3. In **Settings → Integrations**, map a disposable GitHub App repository to a
   disposable site and confirm **Draft PR ready**.
4. Confirm the AI gateway data-sharing boundary is approved for that repository.
5. Set `GITHUB_PATCH_PLANNING_ENABLED=true` on every service that can run the
   Technical Finding pipeline, then redeploy together.
6. Confirm `/health` reports `github_patch_planning=enabled` and Settings shows
   **Exact patch planning ready**.

## Manual UI test — upgrade the existing simulation action

1. Use a disposable repository with a conventional static route such as
   `frontend/app/page.tsx`. Put one `<Image>` or `<img>` without an `alt`
   attribute either in that route or in one locally imported component, then
   deploy that revision to the disposable site.
2. Open the site in the operator and select **Crawl Site**.
3. Open **Technical Findings** and select **Refresh findings**.
4. Find **Images are missing alternative text**.
5. If an older active simulation action exists, refresh once after the new
   rollout. Confirm the older action becomes **Cancelled** and the finding now
   displays **GitHub patch ready** plus the resolved source path.
6. Select **Review GitHub patch**.
7. Confirm:
   - Adapter is `github`;
   - the patch card says **Exact GitHub patch ready for review**;
   - policy state is **Needs approval**;
   - `proposed_diff.files` contains exactly one source path, operation `update`,
     complete replacement content and a 40-character `expected_sha`;
   - the added alt text is accurate and not invented from unrelated content.
8. Select **Approve**, then **Queue execution**.
9. Wait for execute and validate jobs to succeed.
10. Select **Open draft PR** and confirm the PR is draft, unmerged and contains
    only the reviewed file change.
11. Before merging, select **Queue rollback** and confirm the draft PR closes
    and its unchanged governed branch is deleted.

## Negative UI checks

- An unsupported or multi-URL finding shows **Simulation fallback** with a reason.
- An ambiguous repository containing two equally ranked route files stays simulation-only.
- Missing repository authorization, permissions, AI configuration or source
  content never creates a GitHub action.
- Invalid AI JSON, empty content, excessive diff size or failed finding
  postcondition stays simulation-only.
- A decorative `<img alt="" aria-hidden="true">` does not create an image-alt
  finding after a fresh crawl.
- A source file changed after planning fails execution with a stale-object error;
  the worker must not overwrite it.
- Refresh replay reuses the same patch action for the same finding revision and
  expected blob SHA.
- No generated action may target `.github/**`, `.env*`, keys, certificates,
  `wp-config.php`, dependencies, generated output or public assets.

## Rollback of the release

1. Set `GITHUB_PATCH_PLANNING_ENABLED=false` on all planning services.
2. Keep already-created GitHub actions for audit; cancel unapproved actions from
   the UI if their source content should no longer be reviewed.
3. Existing simulation and governed execution continue independently.
4. No database downgrade is required.
