from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text

from app.config import get_settings
from app.database import engine
from app.routers import (
    actions,
    agent,
    auth,
    billing,
    chat,
    crawl,
    execution_jobs,
    github_app,
    github_repository,
    google_data,
    integrations,
    onboarding,
    operator_actions,
    public_audits,
    site_claims,
    sites,
    technical_findings,
    workspaces,
)
from app.services.entitlement_service import QuotaExceededError
from app.services.scheduler import (
    start_crawl_worker,
    start_execution_worker,
    start_search_sync_worker,
    start_url_inspection_worker,
    start_scheduler,
    stop_scheduler,
)
from app.services.rendered_crawler import verify_renderer_runtime

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.crawler_render_enabled:
        await verify_renderer_runtime()
    if settings.scheduler_enabled:
        start_scheduler()
    if settings.execution_worker_enabled:
        start_execution_worker()
    if settings.crawl_worker_enabled:
        start_crawl_worker()
    if settings.search_sync_worker_enabled:
        start_search_sync_worker()
    if settings.url_inspection_worker_enabled:
        start_url_inspection_worker()

    yield

    if (
        settings.scheduler_enabled
        or settings.execution_worker_enabled
        or settings.crawl_worker_enabled
        or settings.search_sync_worker_enabled
        or settings.url_inspection_worker_enabled
    ):
        stop_scheduler()
    await engine.dispose()


app = FastAPI(
    title="SERP Strategists Operator API",
    version="0.18.1",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan,
)

@app.exception_handler(QuotaExceededError)
async def quota_exceeded_handler(request: Request, exc: QuotaExceededError):
    del request
    return JSONResponse(
        status_code=402,
        content={
            "detail": {
                "code": "quota_exceeded",
                "message": str(exc),
                "metric": exc.metric,
                "limit": exc.limit,
                "used": exc.current,
                "requested": exc.requested,
            }
        },
    )


@app.middleware("http")
async def enforce_governed_execution(request: Request, call_next):
    """Reject every legacy action mutation that bypasses the Phase 3 lifecycle."""
    path = request.url.path
    legacy_mutation = (
        path.startswith("/actions/codex/")
        or path.startswith("/actions/fix-plan")
        or path.startswith("/actions/approve-and-execute/")
        or (path.startswith("/actions/fix/") and request.method.upper() != "GET")
    )
    if legacy_mutation:
        return JSONResponse(
            status_code=410,
            content={
                "detail": (
                    "Legacy action mutation is disabled. Create an operator action, apply deterministic "
                    "policy, record approval where required, and execute through a governed adapter."
                )
            },
        )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(public_audits.router)
app.include_router(auth.router)
app.include_router(workspaces.router)
app.include_router(billing.router)
app.include_router(onboarding.router)
app.include_router(google_data.router)
app.include_router(google_data.callback_router)
app.include_router(github_app.router)
app.include_router(github_repository.router)
app.include_router(integrations.router)
app.include_router(site_claims.router)
app.include_router(sites.router)
app.include_router(crawl.router)
app.include_router(agent.router)
app.include_router(operator_actions.router)
app.include_router(technical_findings.router)
app.include_router(execution_jobs.action_router)
app.include_router(execution_jobs.job_router)
app.include_router(actions.router)
app.include_router(chat.router)


@app.get("/health", tags=["system"])
async def health():
    return {
        "status": "ok",
        "service": "serp-strategists-api",
        "version": app.version,
        "environment": settings.app_env,
        "crawler": "first_party",
        "librecrawl": "optional" if settings.librecrawl_enabled else "disabled",
        "execution_worker": "enabled" if settings.execution_worker_enabled else "disabled",
        "github_execution": "enabled" if settings.github_execution_enabled else "disabled",
        "github_patch_planning": "enabled" if settings.github_patch_planning_enabled else "disabled",
        "crawl_worker": "enabled" if settings.crawl_worker_enabled else "disabled",
        "search_sync_worker": "enabled" if settings.search_sync_worker_enabled else "disabled",
        "url_inspection_worker": "enabled" if settings.url_inspection_worker_enabled else "disabled",
        "javascript_rendering": "enabled" if settings.crawler_render_enabled else "disabled",
    }


@app.get("/ready", tags=["system"])
async def readiness():
    checks: dict[str, str] = {}

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # pragma: no cover
        checks["database"] = f"error:{type(exc).__name__}"

    if settings.redis_url:
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            await redis.ping()
            checks["redis"] = "ok"
        except Exception as exc:  # pragma: no cover
            checks["redis"] = f"error:{type(exc).__name__}"
        finally:
            await redis.aclose()
    else:
        checks["redis"] = "not_configured"

    checks["javascript_rendering"] = (
        "startup_verified" if settings.crawler_render_enabled else "disabled"
    )

    is_ready = checks["database"] == "ok" and checks["redis"] in {"ok", "not_configured"}
    payload = {"status": "ready" if is_ready else "not_ready", "checks": checks}
    return JSONResponse(status_code=200 if is_ready else 503, content=payload)
