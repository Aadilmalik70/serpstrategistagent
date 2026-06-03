import uuid
import asyncio

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, async_session_factory
from app.models.site import Site
from app.models.crawl_snapshot import CrawlSnapshot
from app.models.job_queue import JobQueue
from app.services.crawler import run_crawl

router = APIRouter(prefix="/crawl", tags=["crawl"])


class CrawlRequest(BaseModel):
    site_id: uuid.UUID


class CrawlResponse(BaseModel):
    job_id: str
    status: str


async def _run_crawl_background(site_id: uuid.UUID, domain: str):
    """Run crawl in background using a new database session."""
    async with async_session_factory() as db:
        await run_crawl(db, site_id, domain)
        # Update site status to ready
        site = await db.get(Site, site_id)
        if site:
            site.status = "ready"
            await db.commit()


@router.post("/site", response_model=CrawlResponse)
async def start_crawl(
    data: CrawlRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    # Verify site exists
    site = await db.get(Site, data.site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    # Create job record
    job = JobQueue(
        site_id=site.id,
        job_type="crawl",
        status="running",
    )
    db.add(job)

    # Update site status
    site.status = "crawling"
    await db.commit()
    await db.refresh(job)

    # Start crawl in background
    background_tasks.add_task(_run_crawl_background, site.id, site.domain)

    return CrawlResponse(job_id=str(job.id), status="running")


@router.get("/{job_id}")
async def get_crawl_status(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    job = await db.get(JobQueue, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Get latest snapshot for this site
    result = await db.execute(
        select(CrawlSnapshot)
        .where(CrawlSnapshot.site_id == job.site_id)
        .order_by(CrawlSnapshot.started_at.desc())
        .limit(1)
    )
    snapshot = result.scalar_one_or_none()

    return {
        "job_id": str(job.id),
        "status": snapshot.status if snapshot else job.status,
        "pages_discovered": snapshot.pages_discovered if snapshot else 0,
        "pages_crawled": snapshot.pages_crawled if snapshot else 0,
        "errors": snapshot.errors if snapshot else 0,
    }
