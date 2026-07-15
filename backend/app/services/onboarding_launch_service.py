from __future__ import annotations

from datetime import datetime, timezone
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models.google_data_connection import GoogleDataConnection
from app.models.job_queue import JobQueue
from app.models.site import Site
from app.services.crawl_job_service import ACTIVE_CRAWL_STATUSES, enqueue_crawl_job
from app.services.google_baseline_service import sync_google_baseline
from app.services.google_data_service import GoogleDataServiceError, get_connection
from app.services.site_service import get_site_by_id


async def queue_initial_crawl(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    site_id: uuid.UUID,
) -> tuple[JobQueue, Site, int, bool]:
    site = await get_site_by_id(db, site_id, workspace_id)
    if not site:
        raise ValueError("Onboarding site not found")

    existing = await db.scalar(
        select(JobQueue)
        .where(
            JobQueue.site_id == site.id,
            JobQueue.job_type == "crawl",
            JobQueue.status.in_(ACTIVE_CRAWL_STATUSES),
        )
        .order_by(JobQueue.created_at.desc())
        .limit(1)
    )
    if existing:
        payload = existing.payload or {}
        return existing, site, int(payload.get("max_pages") or 100), False

    max_pages = 100
    job, reused = await enqueue_crawl_job(
        db,
        workspace_id=workspace_id,
        site=site,
        max_pages=max_pages,
        source="onboarding",
    )
    await db.refresh(site)
    return job, site, int((job.payload or {}).get("max_pages") or max_pages), not reused


async def run_google_baseline_background(connection_id: uuid.UUID) -> None:
    async with async_session_factory() as db:
        connection = await db.get(GoogleDataConnection, connection_id)
        if not connection:
            return
        try:
            await sync_google_baseline(db, connection)
        except GoogleDataServiceError as exc:
            connection.baseline_status = "failed"
            connection.last_error = str(exc)[:500]
            connection.last_synced_at = datetime.now(timezone.utc)
            await db.commit()
        except Exception as exc:
            connection.baseline_status = "failed"
            connection.last_error = f"Google baseline failed: {type(exc).__name__}"[:500]
            connection.last_synced_at = datetime.now(timezone.utc)
            await db.commit()


async def google_launch_connection(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
) -> GoogleDataConnection | None:
    connection = await get_connection(db, workspace_id, user_id)
    if not connection or connection.status not in {"connected", "configured"}:
        return None
    if not connection.gsc_property and not connection.ga4_property_id:
        return None
    connection.baseline_status = "queued"
    connection.last_error = None
    await db.commit()
    await db.refresh(connection)
    return connection
