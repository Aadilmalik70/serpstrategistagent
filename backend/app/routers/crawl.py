import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.models.crawl_snapshot import CrawlSnapshot
from app.models.job_queue import JobQueue
from app.models.site import Site
from app.services.crawl_job_service import (
    ACTIVE_CRAWL_STATUSES,
    CrawlJobServiceError,
    enqueue_crawl_job,
    request_crawl_cancellation,
    resume_crawl_job,
)
from app.services.site_service import get_site_by_id

router = APIRouter(prefix="/crawl", tags=["crawl"])


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
        "status": job.status,
        "adapter": result.get("adapter") or (job.payload or {}).get("adapter") or "first_party",
        "pages_discovered": int(snapshot.pages_discovered or 0) if snapshot else int(result.get("pages_discovered") or 0),
        "pages_crawled": int(snapshot.pages_crawled or 0) if snapshot else int(result.get("pages_crawled") or 0),
        "errors": int(snapshot.errors or 0) if snapshot else int(result.get("errors") or 0),
        "error": job.error_message or result.get("error") or _snapshot_error(snapshot),
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "cancellation_requested": job.cancellation_requested,
        "lease_expires_at": job.lease_expires_at,
        "heartbeat_at": job.heartbeat_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "details": (snapshot.extracted_data or {}) if snapshot else result.get("details", {}),
    }


@router.post("/site", response_model=CrawlResponse, status_code=202)
async def start_crawl(
    data: CrawlRequest,
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

    requested_max = data.max_pages or 100

    job, reused = await enqueue_crawl_job(
        db,
        workspace_id=context.workspace.id,
        site=site,
        max_pages=requested_max,
        source="manual",
    )
    return CrawlResponse(job_id=str(job.id), status=job.status, reused=reused)


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
            .where(
                JobQueue.id == job_id,
                JobQueue.job_type == "crawl",
                Site.workspace_id == context.workspace.id,
            )
        )
    ).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return await _crawl_status_payload(db, job)


@router.post("/{job_id}/cancel")
async def cancel_crawl(
    job_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    require_workspace_role(context, "owner", "admin")
    try:
        job = await request_crawl_cancellation(
            db,
            workspace_id=context.workspace.id,
            job_id=job_id,
        )
    except CrawlJobServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return await _crawl_status_payload(db, job)


@router.post("/{job_id}/resume", status_code=202)
async def resume_crawl(
    job_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    require_workspace_role(context, "owner", "admin")
    try:
        job = await resume_crawl_job(
            db,
            workspace_id=context.workspace.id,
            job_id=job_id,
        )
    except CrawlJobServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return await _crawl_status_payload(db, job)
