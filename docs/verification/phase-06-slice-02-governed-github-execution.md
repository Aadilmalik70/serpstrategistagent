# Phase 6 Slice 2 — Governed GitHub execution

## Release boundary

- Migration: `022`
- API: `0.17.0`
- Provider mutation: GitHub App installation token only
- Result: deterministic branch, commit, and **draft** pull request
- Still disabled: autonomous merge, force-push, workflow/secret changes, WordPress mutation

## GitHub App permissions

The installation must grant:

- Repository permissions → Contents: **Read and write**
- Repository permissions → Pull requests: **Read and write**
- Repository permissions → Metadata: **Read-only**

Only repositories selected for the installation can be mapped or mutated.

## Exact action contract

The approved `OperatorAction` must use a GitHub execution target and a complete
text-file plan. Patch generation is outside the execution worker; the worker
does not ask an LLM to modify the approved plan.

```json
{
  "execution_target": {
    "adapter": "github",
    "base_branch": "main"
  },
  "proposed_diff": {
    "commit_message": "Refresh landing-page metadata",
    "files": [
      {
        "path": "content/homepage.md",
        "operation": "update",
        "content": "Complete replacement UTF-8 text",
        "expected_sha": "optional-current-Git-blob-SHA"
      }
    ]
  }
}
```

Supported operations are `create`, `update`, and `delete`. Create and update
require complete UTF-8 content. Delete cannot contain content. Paths must be
repository-relative and unique within the plan.

Protected paths include `.git/**`, `.github/**`, `.env*`, private-key formats,
`wp-config.php`, and traversal or absolute paths. The adapter repeats this check
at execution time even if the policy record was tampered with.

Default limits:

- 20 files per action
- 256 KiB per file
- 1 MiB total proposed content

## Deployment

1. Deploy API and worker from the same commit with:

   ```env
   GITHUB_EXECUTION_ENABLED=false
   EXECUTION_WORKER_ENABLED=false
   ```

2. Apply migration `022`.
3. Confirm `/health` reports API `0.17.0` and `github_execution=disabled`.
4. Confirm the GitHub App installation has the required permissions and map a
   disposable sandbox repository to a disposable site.
5. Enable `EXECUTION_WORKER_ENABLED=true` on exactly one worker service.
6. Set `GITHUB_EXECUTION_ENABLED=true` on API and execution worker so enqueue
   preflight and worker execution use the same gate, then redeploy them together.
7. Confirm `/health` reports `github_execution=enabled`.

Do not place `GITHUB_APP_PRIVATE_KEY_BASE64` in the frontend service.

## UI smoke test

### Prerequisites

1. Use a disposable repository and a disposable site mapping. Do not test the
   first rollout against the product repository.
2. Apply migration `022`, deploy the API and worker from the same commit, and
   enable both `EXECUTION_WORKER_ENABLED=true` and
   `GITHUB_EXECUTION_ENABLED=true` on those services.
3. Connect the GitHub App at **Settings → Integrations**, select the disposable
   repository, and map it to the test site.
4. Confirm the repository card shows **Draft PR ready**. If it does not, stop:
   the App permissions, installation, mapping, or rollout flags are incomplete.

### Create the test action

The current Technical Findings UI creates simulation actions; it does not yet
author arbitrary full-file GitHub patches. For this slice, create one governed
test action through the API (or an approved fixture) with the exact contract
shown above, then copy its returned `id`. Use a harmless file such as
`docs/serp-operator-smoke.md`, an idempotency key unique to the run, and the
disposable site's `site_id`.

Do not substitute a generated recommendation for the exact `proposed_diff.files`
contract. The worker must execute only content that was visible during approval.

### Browser workflow

1. Open **Actions** and select the test action, or browse directly to
   `/actions/<action-id>`.
2. Expand **Execution target** and **Proposed diff**. Confirm the adapter is
   `github`, the base branch is correct, and every path/content value matches
   the intended disposable-repository change.
3. Select **Run policy & propose**. GitHub actions must enter
   **Needs approval** even
   when their original action type is otherwise auto-approvable.
4. Confirm the policy reason says repository mutation needs explicit operator
   approval, then select **Approve**.
5. Select **Queue execution**. Open the execution job and wait for both the
   execute and validate jobs to succeed; refresh if the worker is asynchronous.
6. Return to the action and confirm it displays **Open draft PR**.
7. Follow that link and verify in GitHub:
   - the branch name starts with `serp-operator/action-`;
   - one non-merge commit contains the approved file changes;
   - the pull request is a draft;
   - the target is the snapshotted base branch;
   - no protected file changed;
   - no merge occurred.
8. Return to the action and select **Queue rollback** before merging. Confirm
    the draft PR closes and
    the unchanged action branch is deleted.

### Browser negative test

Create a second draft action that targets `.github/workflows/smoke.yml` or
`.env.production`. Open it in **Actions**, select **Run policy & propose**, and
confirm the action becomes **Blocked**. No execution job, branch, commit, or pull
request may be created.

## Negative checks

- An unapproved action cannot enqueue.
- A public mapping without a GitHub App installation cannot execute.
- Missing Contents/Pull requests write permissions fail preflight.
- A changed base branch or mismatched `expected_sha` fails without mutation.
- Protected paths fail before any provider request.
- Replaying an already-created action reuses its deterministic branch/PR.
- A branch advanced by a human is never force-pushed or deleted.
- A merged PR cannot use draft-branch rollback; it requires a new reviewed
  revert action.
- Installation tokens never appear in action, job, snapshot, log, or browser
  responses.
- Draft-PR creation records `site_mutation_applied=false`; measurement learning
  must wait for a later deploy-status slice.

## Rollback of the release

1. Set `GITHUB_EXECUTION_ENABLED=false` on API and worker.
2. Let active execution jobs finish or cancel queued jobs from the UI.
3. Keep migration `022`; it is additive and preserves the audit record.
4. Close any remaining sandbox draft PRs manually if provider execution stopped
   between PR creation and database persistence.
5. Revert application code only after the rollout gate is disabled.

Downgrading migration `022` deletes GitHub execution audit records and should
not be used as the normal production rollback.
