from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory, get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.models.crawl_snapshot import CrawlSnapshot
from app.models.job_queue import JobQueue
from app.models.site import Site
from app.services.crawler import run_crawl
from app.services.entitlement_service import assert_usage_quota, effective_entitlements, record_usage
from app.services.site_service import get_site_by_id

router = APIRouter(prefix="/crawl", tags=["crawl"])
ACTIVE_CRAWL_STATUSES = {"queued", "running"}


class CrawlRequest(BaseModel):
    site_id: uuid.UUID
    max_pages: int | None = Field(default=None, ge=1, le=100_000)


class CrawlResponse(BaseModel):
    job_id: str
    status: str
    reused: bool = False


def _snapshot_error(snapshot: CrawlSnapshot | None) -> str | None:
    if not snapshot:
        return None
    data = snapshot.extracted_data or {}
    value = data.get("error")
    if isinstance(value, str):
        return value
    errors = data.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            return str(first.get("message") or first.get("type") or "Crawl failed")
    return None


async def run_crawl_job(
    workspace_id: uuid.UUID,
    site_id: uuid.UUID,
    domain: str,
    max_pages: int,
    job_id: uuid.UUID,
) -> None:
    """Run one persisted first-party crawl job and record every terminal state."""
    try:
        async with async_session_factory() as db:
            job = await db.get(JobQueue, job_id)
            site = await db.get(Site, site_id)
            if not job or not site or site.workspace_id != workspace_id:
                return
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            site.status = "crawling"
            await db.commit()

        async with async_session_factory() as db:
            snapshot = await run_crawl(
                db,
                site_id,
                domain,
                max_pages=max_pages,
                job_id=job_id,
            )
            pages_crawled = int(snapshot.pages_crawled or 0)
            job = await db.get(JobQueue, job_id)
            site = await db.get(Site, site_id)
            if not job or not site:
                return

            result = {
                "adapter": "first_party",
                "snapshot_id": str(snapshot.id),
                "pages_discovered": int(snapshot.pages_discovered or 0),
                "pages_crawled": pages_crawled,
                "errors": int(snapshot.errors or 0),
                "details": snapshot.extracted_data or {},
            }
            job.result = result
            job.completed_at = datetime.now(timezone.utc)

            if snapshot.status == "completed" and pages_crawled > 0:
                job.status = "completed"
                site.status = "ready"
                await record_usage(
                    db,
                    workspace_id=workspace_id,
                    site_id=site_id,
                    metric="monthly_crawl_pages",
                    quantity=pages_crawled,
                    purpose="site_crawl",
                    details={"adapter": "first_party", "snapshot_id": str(snapshot.id)},
                    commit=False,
                )
            else:
                job.status = "failed"
                site.status = "crawl_failed"
            await db.commit()
    except Exception as exc:
        async with async_session_factory() as db:
            job = await db.get(JobQueue, job_id)
            site = await db.get(Site, site_id)
            if job:
                job.status = "failed"
                job.completed_at = datetime.now(timezone.utc)
                job.result = {
                    "adapter": "first_party",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:1000],
                }
            if site:
                site.status = "crawl_failed"
            await db.commit()


async def _crawl_status_payload(db: AsyncSession, job: JobQueue) -> dict:
    snapshot: CrawlSnapshot | None = None
    snapshot_id = (job.payload or {}).get("snapshot_id")
    if snapshot_id:
        try:
            snapshot = await db.get(CrawlSnapshot, uuid.UUID(str(snapshot_id)))
        except (ValueError, TypeError):
            snapshot = None
    if snapshot is None:
        snapshot = (
            await db.execute(
                select(CrawlSnapshot)
                .where(
                    CrawlSnapshot.site_id == job.site_id,
                    CrawlSnapshot.started_at >= job.created_at,
                )
                .order_by(CrawlSnapshot.started_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    result = job.result or {}
    return {
        "job_id": str(job.id),
        "site_id": str(job.site_id),
        "status": job.status if job.status in {"completed", "failed", "cancelled"} else (snapshot.status if snapshot else job.status),
        "adapter": result.get("adapter") or (job.payload or {}).get("adapter") or "first_party",
        "pages_discovered": int(snapshot.pages_discovered or 0) if snapshot else int(result.get("pages_discovered") or 0),
        "pages_crawled": int(snapshot.pages_crawled or 0) if snapshot else int(result.get("pages_crawled") or 0),
        "errors": int(snapshot.errors or 0) if snapshot else int(result.get("errors") or 0),
        "error": result.get("error") or _snapshot_error(snapshot),
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "details": (snapshot.extracted_data or {}) if snapshot else result.get("details", {}),
    }


@router.post("/site", response_model=CrawlResponse, status_code=202)
async def start_crawl(
    data: CrawlRequest,
    background_tasks: BackgroundTasks,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> CrawlResponse:
    require_workspace_role(context, "owner", "admin")
    site = await get_site_by_id(db, data.site_id, context.workspace.id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    active = await db.scalar(
        select(JobQueue)
        .where(
            JobQueue.site_id == site.id,
            JobQueue.job_type == "crawl",
            JobQueue.status.in_(ACTIVE_CRAWL_STATUSES),
        )
        .order_by(JobQueue.created_at.desc())
    )
    if active:
        return CrawlResponse(job_id=str(active.id), status=active.status, reused=True)

    subscription, _, current = await assert_usage_quota(
        db,
        workspace_id=context.workspace.id,
        metric="monthly_crawl_pages",
        requested=1,
    )
    limit = int(effective_entitlements(subscription)["monthly_crawl_pages"])
    remaining = max(0, limit - current)
    requested_max = data.max_pages or 100
    max_pages = min(requested_max, remaining)
    if max_pages < 1:
        raise HTTPException(status_code=402, detail="No crawl-page capacity remains in this billing period")

    job = JobQueue(
        site_id=site.id,
        job_type="crawl",
        status="queued",
        payload={
            "adapter": "first_party",
            "max_pages": max_pages,
            "workspace_id": str(context.workspace.id),
        },
    )
    db.add(job)
    site.status = "crawl_queued"
    await db.commit()
    await db.refresh(job)

    background_tasks.add_task(
        run_crawl_job,
        context.workspace.id,
        site.id,
        site.domain,
        max_pages,
        job.id,
    )
    return CrawlResponse(job_id=str(job.id), status="queued")


@router.get("/site/{site_id}/latest")
async def get_latest_crawl(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    site = await get_site_by_id(db, site_id, context.workspace.id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    job = await db.scalar(
        select(JobQueue)
        .where(JobQueue.site_id == site_id, JobQueue.job_type == "crawl")
        .order_by(JobQueue.created_at.desc())
    )
    if not job:
        return {
            "site_id": str(site_id),
            "status": "not_started",
            "pages_discovered": 0,
            "pages_crawled": 0,
            "errors": 0,
            "error": None,
        }
    return await _crawl_status_payload(db, job)


@router.get("/{job_id}")
async def get_crawl_status(
    job_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    job = (
        await db.execute(
            select(JobQueue)
            .join(Site, Site.id == JobQueue.site_id)
            .where(JobQueue.id == job_id, Site.workspace_id == context.workspace.id)
        )
    ).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return await _crawl_status_payload(db, job)
