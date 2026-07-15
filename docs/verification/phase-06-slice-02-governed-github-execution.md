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

1. Open **Settings → Integrations**.
2. Confirm the mapped sandbox repository shows **Draft PR ready**.
3. Create or select a draft action whose exact file plan targets that site.
4. Run policy evaluation. GitHub actions must require explicit approval even
   when their original action type is otherwise auto-approvable.
5. Approve the action.
6. Select **Queue execution**.
7. Wait for the execute and validate jobs to succeed.
8. Confirm the action displays **Open draft PR**.
9. In GitHub, verify:
   - the branch name starts with `serp-operator/action-`;
   - one non-merge commit contains the approved file changes;
   - the pull request is a draft;
   - the target is the snapshotted base branch;
   - no protected file changed;
   - no merge occurred.
10. Select **Queue rollback** before merging. Confirm the draft PR closes and
    the unchanged action branch is deleted.

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
