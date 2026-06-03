"""Scheduler for periodic agent runs using APScheduler."""
import logging
import uuid
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.database import async_session_factory
from app.models.site import Site
from app.models.agent_run import AgentRun
from app.services.agent_graph import run_agent_graph
from app.services.fix_executor import execute_fix_action
from app.services.fix_governance import RiskAssessment
from app.services.fix_planner import generate_bulk_fix_plans

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def scheduled_agent_run():
    """Run agent analysis for all sites with status='ready'."""
    logger.info("Scheduler: Starting periodic agent run for all sites")

    async with async_session_factory() as db:
        result = await db.execute(
            select(Site).where(Site.status == "ready")
        )
        sites = list(result.scalars().all())

    if not sites:
        logger.info("Scheduler: No sites ready for analysis")
        return

    for site in sites:
        try:
            # Create agent run record
            async with async_session_factory() as db:
                agent_run = AgentRun(
                    site_id=site.id,
                    status="running",
                    trigger="scheduled",
                )
                db.add(agent_run)
                await db.commit()
                await db.refresh(agent_run)
                run_id = agent_run.id

            logger.info(f"Scheduler: Running agent for {site.domain} (run {run_id})")
            await run_agent_graph(site.id, run_id)
            async with async_session_factory() as db:
                fixes = await generate_bulk_fix_plans(db, site.id, max_issues=5)
                autonomous_enabled = bool((site.site_context or {}).get("autonomous_enabled", False))

                for fix in fixes:
                    fix_content = fix.fix_content or {}
                    governance = fix_content.get("governance") or {}
                    risk = RiskAssessment(
                        score=int(governance.get("risk_score") or 0),
                        level=governance.get("risk_level", "medium"),
                        reasons=list(governance.get("risk_reasons", [])),
                        requires_human_approval=bool(governance.get("requires_human_approval", True)),
                    )
                    mode = "auto_execute" if autonomous_enabled and not risk.requires_human_approval else "needs_approval"
                    if mode == "auto_execute":
                        fix.status = "approved"
                        fix.approved_at = datetime.now(timezone.utc)
                        await db.commit()
                        await execute_fix_action(db, fix.id)

            logger.info(f"Scheduler: Completed full loop (observe/analyze/plan/execute/evaluate) for {site.domain}")

        except Exception as e:
            logger.error(f"Scheduler: Failed for {site.domain}: {e}")


def start_scheduler():
    """Start the APScheduler with 24h interval."""
    scheduler.add_job(
        scheduled_agent_run,
        trigger=IntervalTrigger(hours=24),
        id="daily_agent_run",
        name="Daily SEO agent analysis",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started: agent will run every 24 hours")


def stop_scheduler():
    """Shutdown the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
