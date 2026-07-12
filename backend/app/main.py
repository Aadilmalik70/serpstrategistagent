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
    google_data,
    integrations,
    onboarding,
    site_claims,
    sites,
    workspaces,
)
from app.services.entitlement_service import QuotaExceededError
from app.services.scheduler import start_scheduler, stop_scheduler

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.scheduler_enabled:
        start_scheduler()

    yield

    if settings.scheduler_enabled:
        stop_scheduler()
    await engine.dispose()


app = FastAPI(
    title="SERP Strategists Operator API",
    version="0.6.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    """Disable the legacy direct-Codex endpoint that bypasses operator governance."""
    if request.url.path.startswith("/actions/codex/"):
        return JSONResponse(
            status_code=410,
            content={
                "detail": (
                    "Direct code execution is disabled. Create an operator action, "
                    "apply policy checks, obtain approval where required, and execute through a governed adapter."
                )
            },
        )
    return await call_next(request)


app.include_router(auth.router)
app.include_router(workspaces.router)
app.include_router(billing.router)
app.include_router(onboarding.router)
app.include_router(google_data.router)
app.include_router(google_data.callback_router)
app.include_router(integrations.router)
app.include_router(site_claims.router)
app.include_router(sites.router)
app.include_router(crawl.router)
app.include_router(agent.router)
app.include_router(actions.router)
app.include_router(chat.router)


@app.get("/health", tags=["system"])
async def health():
    """Liveness check: the API process can accept requests."""
    return {
        "status": "ok",
        "service": "serp-strategists-api",
        "version": app.version,
        "environment": settings.app_env,
    }


@app.get("/ready", tags=["system"])
async def readiness():
    """Readiness check for database and optional Redis dependencies."""
    checks: dict[str, str] = {}

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # pragma: no cover - exact driver errors vary by environment
        checks["database"] = f"error:{type(exc).__name__}"

    if settings.redis_url:
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            await redis.ping()
            checks["redis"] = "ok"
        except Exception as exc:  # pragma: no cover - exact driver errors vary by environment
            checks["redis"] = f"error:{type(exc).__name__}"
        finally:
            await redis.aclose()
    else:
        checks["redis"] = "not_configured"

    is_ready = checks["database"] == "ok" and checks["redis"] in {"ok", "not_configured"}
    payload = {"status": "ready" if is_ready else "not_ready", "checks": checks}
    return JSONResponse(status_code=200 if is_ready else 503, content=payload)
