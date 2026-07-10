# Phase 1 — Foundation and Railway Staging Verification

This phase creates a reproducible deployment foundation. Do not connect production domains or production credentials yet.

## What this phase includes

- Separate production containers for the Next.js frontend and FastAPI backend
- PostgreSQL and Redis local parity through Docker Compose
- Backend liveness and dependency-readiness endpoints
- Frontend health endpoint
- Database migrations as a Railway pre-deploy command
- GitHub Actions checks for backend and frontend
- A hard block on the legacy direct-Codex execution route
- Scheduler disabled by default until durable governed workflows replace it

## Railway project layout

Create one Railway project named `serp-strategists-staging` with four services:

1. `web` — GitHub repository service, root directory `/frontend`
2. `api` — GitHub repository service, root directory `/backend`
3. `Postgres` — Railway PostgreSQL database
4. `Redis` — Railway Redis database

Both `web` and `api` should connect to `Aadilmalik70/serpstrategistagent` and use the branch `phase/01-foundation-staging` while this PR is under review.

## API service settings

Set:

- Root directory: `/backend`
- Railway config file: `/backend/railway.toml`
- Healthcheck path: `/ready`
- Trigger branch: `phase/01-foundation-staging`

Variables:

```env
APP_ENV=staging
DEBUG=false
FRONTEND_URL=https://<web-service-domain>
CORS_ORIGINS=https://<web-service-domain>
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
SECRET_KEY=<random-value-at-least-32-characters>
SCHEDULER_ENABLED=false
LIBRECRAWL_ENABLED=false
```

Do not add OpenAI, Gemini, SerpAPI, Google, Stripe, GitHub App, or WordPress secrets in this phase.

## Web service settings

Set:

- Root directory: `/frontend`
- Railway config file: `/frontend/railway.toml`
- Healthcheck path: `/api/health`
- Trigger branch: `phase/01-foundation-staging`

Variables:

```env
NEXT_PUBLIC_API_URL=https://<api-service-domain>
NEXTAUTH_URL=https://<web-service-domain>
NEXTAUTH_SECRET=<random-secret>
AUTH_EMAIL=<temporary-test-email>
AUTH_PASSWORD=<temporary-strong-password>
```

Because `NEXT_PUBLIC_API_URL` is used by browser code, redeploy the web service after changing it.

## Recommended deployment order

1. Provision PostgreSQL and Redis.
2. Deploy the API service.
3. Generate a Railway domain for the API.
4. Deploy the web service with `NEXT_PUBLIC_API_URL` set to the API domain.
5. Generate a Railway domain for the web service.
6. Update `FRONTEND_URL`, `CORS_ORIGINS`, and `NEXTAUTH_URL` with the final web domain.
7. Redeploy both services.
8. Enable Railway `Wait for CI` after the GitHub Actions workflow is visible.

## Manual verification

### GitHub

- [ ] Draft PR exists from `phase/01-foundation-staging` to `main`
- [ ] Backend CI passes
- [ ] Frontend CI passes
- [ ] No secrets appear in the PR diff

### API

- [ ] `GET /health` returns HTTP 200 and `status: ok`
- [ ] `GET /ready` returns HTTP 200
- [ ] Readiness response shows `database: ok`
- [ ] Readiness response shows `redis: ok`
- [ ] `POST /actions/codex/<uuid>` returns HTTP 410
- [ ] API logs show migrations completed before application startup

### Web

- [ ] `GET /api/health` returns HTTP 200
- [ ] Login page loads
- [ ] Temporary credentials allow login
- [ ] Dashboard loads without a browser CORS error
- [ ] Existing site screens remain reachable

### Local optional check

From the repository root:

```bash
docker compose up --build
```

Then check:

- Web: `http://localhost:3000`
- API liveness: `http://localhost:8000/health`
- API readiness: `http://localhost:8000/ready`

Temporary local login:

```text
Email: admin@example.com
Password: admin123
```

Never reuse these local credentials on Railway.

## Approval response

When all required checks pass, reply:

```text
APPROVE PHASE 1
```

When something fails, reply:

```text
PHASE 1 BUGS
1. Describe the failed checklist item
2. Include the Railway deployment log or browser error
```
