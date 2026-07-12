import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_factory, get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.models.crawl_snapshot import CrawlSnapshot
from app.models.job_queue import JobQueue
from app.models.site import Site
from app.services import librecrawl
from app.services.crawler import run_crawl
from app.services.entitlement_service import assert_usage_quota, effective_entitlements, record_usage
from app.services.site_service import get_site_by_id

router = APIRouter(prefix="/crawl", tags=["crawl"])


class CrawlRequest(BaseModel):
    site_id: uuid.UUID


class CrawlResponse(BaseModel):
    job_id: str
    status: str


async def _run_crawl_background(
    workspace_id: uuid.UUID,
    site_id: uuid.UUID,
    domain: str,
    max_pages: int,
):
    """Run a bounded crawl and record the actual pages consumed against the workspace period."""
    settings = get_settings()
    pages_crawled = 0

    if settings.librecrawl_enabled and await librecrawl.is_available():
        result = await librecrawl.crawl_and_sync_pages(domain, site_id, max_pages=max_pages)
        if "error" not in result:
            pages_crawled = int(result.get("pages_synced") or 0)
            await librecrawl.sync_issues_from_export(site_id, result.get("crawl_id"))
            async with async_session_factory() as db:
                site = await db.get(Site, site_id)
                if site:
                    site.status = "ready"
                if pages_crawled > 0:
                    await record_usage(
                        db,
                        workspace_id=workspace_id,
                        site_id=site_id,
                        metric="monthly_crawl_pages",
                        quantity=pages_crawled,
                        purpose="site_crawl",
                        details={"adapter": "librecrawl"},
                        commit=False,
                    )
                await db.commit()
            return

    async with async_session_factory() as db:
        snapshot = await run_crawl(db, site_id, domain, max_pages=max_pages)
        pages_crawled = int(snapshot.pages_crawled or 0)
        site = await db.get(Site, site_id)
        if site:
            site.status = "ready"
        if pages_crawled > 0:
            await record_usage(
                db,
                workspace_id=workspace_id,
                site_id=site_id,
                metric="monthly_crawl_pages",
                quantity=pages_crawled,
                purpose="site_crawl",
                details={"adapter": "basic"},
                commit=False,
            )
        await db.commit()


@router.post("/site", response_model=CrawlResponse)
async def start_crawl(
    data: CrawlRequest,
    background_tasks: BackgroundTasks,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    require_workspace_role(context, "owner", "admin")
    site = await get_site_by_id(db, data.site_id, context.workspace.id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    subscription, _, current = await assert_usage_quota(
        db,
        workspace_id=context.workspace.id,
        metric="monthly_crawl_pages",
        requested=1,
    )
    limit = int(effective_entitlements(subscription)["monthly_crawl_pages"])
    remaining = max(0, limit - current)
    max_pages = min(100, remaining)

    job = JobQueue(site_id=site.id, job_type="crawl", status="running")
    db.add(job)
    site.status = "crawling"
    await db.commit()
    await db.refresh(job)

    background_tasks.add_task(
        _run_crawl_background,
        context.workspace.id,
        site.id,
        site.domain,
        max_pages,
    )
    return CrawlResponse(job_id=str(job.id), status="running")


@router.get("/{job_id}")
async def get_crawl_status(
    job_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(JobQueue)
        .join(Site, Site.id == JobQueue.site_id)
        .where(JobQueue.id == job_id, Site.workspace_id == context.workspace.id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    snapshot = (
        await db.execute(
            select(CrawlSnapshot)
            .where(CrawlSnapshot.site_id == job.site_id)
            .order_by(CrawlSnapshot.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    return {
        "job_id": str(job.id),
        "status": snapshot.status if snapshot else job.status,
        "pages_discovered": snapshot.pages_discovered if snapshot else 0,
        "pages_crawled": snapshot.pages_crawled if snapshot else 0,
        "errors": snapshot.errors if snapshot else 0,
    }
