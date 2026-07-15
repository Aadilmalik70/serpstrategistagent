# Phase 6 Slice 1 — GitHub App authorization verification

This slice replaces user-supplied GitHub Personal Access Tokens with a
workspace-scoped GitHub App installation. It authorizes and maps public or
private repositories without enabling repository mutation.

## Release boundary

- Migration: `021`
- API version: `0.16.0`
- GitHub App JWTs use `RS256` and expire within ten minutes.
- Installation access tokens are minted server-side, used only for the provider
  request, and never persisted or returned to the browser.
- Installation callback state is random, stored only as a SHA-256 hash, expires
  after ten minutes by default, and can be consumed once.
- Installation and repository records are scoped to one workspace.
- Repository execution stays disabled. No branch, commit, pull request, or
  repository content can be created by this slice.

## GitHub App configuration

Create or update the GitHub App with:

- Homepage URL: the production frontend URL.
- Setup URL: `https://<api-host>/integrations/github-app/callback`.
- Redirect on update: enabled.
- Webhook: inactive for this slice.
- Repository permissions needed by the following governed execution slices:
  `Contents: Read and write` and `Pull requests: Read and write`. Metadata read
  access is implicit. Do not grant administration or organization permissions.

Generate a private key for the App. Base64-encode the complete PEM, including
its header and footer, without line breaks. Store it only as a backend/worker
secret; never expose it through a `NEXT_PUBLIC_` variable.

## Railway variables

Set on every backend replica that can serve integration API requests:

```text
GITHUB_API_URL=https://api.github.com
GITHUB_APP_ID=<numeric App ID>
GITHUB_APP_SLUG=<App URL slug>
GITHUB_APP_PRIVATE_KEY_BASE64=<base64 PEM>
GITHUB_APP_STATE_TTL_MINUTES=10
GITHUB_APP_TIMEOUT_SECONDS=20
FRONTEND_URL=https://<frontend-host>
```

Keep the execution worker setting unchanged. GitHub repository mutations are
rejected independently of `EXECUTION_WORKER_ENABLED` in this slice.

## Deployment

1. Back up the production database.
2. Deploy the backend and run `alembic upgrade head` before directing traffic to
   the new application revision.
3. Confirm `alembic current` reports `021`.
4. Deploy the frontend from the same commit.
5. Confirm `GET /health` succeeds and the OpenAPI version is `0.16.0` when docs
   are enabled.

Migration `021` preserves existing public `sites.github_repo` mappings by
backfilling them into `github_repository_connections` with no App installation.

## UI smoke test

1. Sign in as a workspace owner or admin and open **Settings → Integrations**.
2. Confirm GitHub shows **Not installed** when the backend App configuration is
   present, or **Unavailable** when it is absent.
3. Select **Install GitHub App** and grant one test repository to the App.
4. Confirm GitHub redirects to Settings and shows the installation account as
   **Authorized** and **Execution disabled**.
5. Select **Map repository**, choose a site and the authorized private
   repository, and save.
6. Confirm the repository inventory shows **App authorized**, its visibility and
   default branch, plus **Execution disabled**.
7. Sign into a different workspace and confirm it cannot see the installation or
   use its installation record ID.
8. Disconnect the authorization. Confirm the installation and mapped repository
   become inactive locally and no GitHub repository content changes.

## Expected failure checks

- Reusing or altering callback `state` redirects with
  `github_install_state_invalid`.
- Mapping a repository not returned by the installation returns
  `github_repository_not_authorized`.
- Reusing an installation already owned by another workspace returns
  `github_installation_in_use`.
- Provider authentication failure returns `github_app_authorization_failed`
  without exposing provider tokens or private-key material.
- The legacy `/actions/integrations/{site_id}` GitHub token write returns `410`.

## Rollback

Roll back the frontend and backend together. To disable new installations
without reverting the database, remove all three App identity variables
(`GITHUB_APP_ID`, `GITHUB_APP_SLUG`, and `GITHUB_APP_PRIVATE_KEY_BASE64`) and
redeploy. Existing records remain inert and execution stays disabled. Downgrade
past `021` only after reverting the application and accepting removal of the new
authorization records.
