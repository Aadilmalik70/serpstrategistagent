"""Periodic analysis and durable governed execution worker scheduling."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.config import get_settings
from app.database import async_session_factory
from app.models.agent_run import AgentRun
from app.models.google_data_connection import GoogleDataConnection
from app.models.site import Site
from app.services.agent_graph import run_agent_graph
from app.services.crawl_job_service import run_crawl_worker_tick
from app.services.execution_service import run_execution_worker_tick
from app.services.fix_planner import generate_bulk_fix_plans
from app.services.search_performance_service import enqueue_search_sync, run_search_sync_worker_tick

logger = logging.getLogger(__name__)
settings = get_settings()
scheduler = AsyncIOScheduler()


async def scheduled_agent_run() -> None:
    """Observe and plan for ready sites without bypassing governed execution."""
    logger.info("Scheduler: starting periodic analysis")
    async with async_session_factory() as db:
        sites = list(
            (
                await db.execute(select(Site).where(Site.status == "ready"))
            ).scalars().all()
        )

    for site in sites:
        try:
            async with async_session_factory() as db:
                agent_run = AgentRun(site_id=site.id, status="running", trigger="scheduled")
                db.add(agent_run)
                await db.commit()
                await db.refresh(agent_run)
                run_id = agent_run.id
            await run_agent_graph(site.id, run_id)
            async with async_session_factory() as db:
                await generate_bulk_fix_plans(db, site.id, max_issues=5)
            logger.info("Scheduler: analysis and planning completed for %s", site.domain)
        except Exception:
            logger.exception("Scheduler: analysis failed for %s", site.domain)


async def scheduled_execution_tick() -> None:
    """Claim a bounded batch of durable jobs using database leases."""
    try:
        processed = await run_execution_worker_tick()
        if processed:
            logger.info("Execution worker processed %s job(s)", processed)
    except Exception:
        logger.exception("Execution worker tick failed")


async def scheduled_crawl_tick() -> None:
    """Recover and claim a bounded batch of durable crawl jobs."""
    try:
        processed = await run_crawl_worker_tick()
        if processed:
            logger.info("Crawl worker processed %s job(s)", processed)
    except Exception:
        logger.exception("Crawl worker tick failed")


async def scheduled_search_sync_tick() -> None:
    """Recover and claim a bounded batch of durable Search Console jobs."""
    try:
        processed = await run_search_sync_worker_tick()
        if processed:
            logger.info("Search sync worker processed %s job(s)", processed)
    except Exception:
        logger.exception("Search sync worker tick failed")


async def scheduled_search_sync_enqueue() -> None:
    """Create one idempotent daily Search Console sync per configured site."""
    async with async_session_factory() as db:
        configured = list(
            (
                await db.execute(
                    select(GoogleDataConnection).where(
                        GoogleDataConnection.status == "configured",
                        GoogleDataConnection.gsc_property.is_not(None),
                    )
                )
            ).scalars().all()
        )
        for connection in configured:
            sites = list(
                (
                    await db.execute(
                        select(Site).where(Site.workspace_id == connection.workspace_id)
                    )
                ).scalars().all()
            )
            for site in sites:
                try:
                    await enqueue_search_sync(
                        db,
                        workspace_id=connection.workspace_id,
                        site_id=site.id,
                        source="daily_scheduler",
                    )
                except Exception:
                    await db.rollback()
                    logger.exception("Could not enqueue Search Console sync for %s", site.domain)


def start_scheduler() -> None:
    scheduler.add_job(
        scheduled_agent_run,
        trigger=IntervalTrigger(hours=24),
        id="daily_agent_run",
        name="Daily SEO analysis and planning",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        scheduled_search_sync_enqueue,
        trigger=IntervalTrigger(hours=24),
        id="daily_search_sync_enqueue",
        name="Daily Search Console ingestion",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    if not scheduler.running:
        scheduler.start()
    logger.info("Analysis scheduler started")


def start_execution_worker() -> None:
    scheduler.add_job(
        scheduled_execution_tick,
        trigger=IntervalTrigger(seconds=settings.execution_worker_poll_seconds),
        id="execution_worker_tick",
        name="Governed execution worker",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    if not scheduler.running:
        scheduler.start()
    logger.info("Execution worker started with %ss polling", settings.execution_worker_poll_seconds)


def start_crawl_worker() -> None:
    scheduler.add_job(
        scheduled_crawl_tick,
        trigger=IntervalTrigger(seconds=settings.crawl_worker_poll_seconds),
        id="crawl_worker_tick",
        name="Durable first-party crawl worker",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    if not scheduler.running:
        scheduler.start()
    logger.info("Crawl worker started with %ss polling", settings.crawl_worker_poll_seconds)


def start_search_sync_worker() -> None:
    scheduler.add_job(
        scheduled_search_sync_tick,
        trigger=IntervalTrigger(seconds=settings.search_sync_worker_poll_seconds),
        id="search_sync_worker_tick",
        name="Durable Search Console sync worker",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    if not scheduler.running:
        scheduler.start()
    logger.info("Search sync worker started with %ss polling", settings.search_sync_worker_poll_seconds)


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
