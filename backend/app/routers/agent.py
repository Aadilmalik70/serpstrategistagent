import uuid

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select, case, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, async_session_factory
from app.models.site import Site
from app.models.agent_run import AgentRun
from app.models.issue import Issue
from app.services.agent_graph import run_agent_graph
from app.services.health_score import calculate_health_score

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentRunRequest(BaseModel):
    site_id: uuid.UUID


class AgentRunResponse(BaseModel):
    run_id: str
    status: str


@router.post("/run", response_model=AgentRunResponse)
async def start_agent_run(
    data: AgentRunRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Start an agent analysis run for a site."""
    site = await db.get(Site, data.site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    # Create initial run record to return ID
    agent_run = AgentRun(site_id=site.id, status="running", trigger="manual")
    db.add(agent_run)
    await db.commit()
    await db.refresh(agent_run)

    # Start in background
    background_tasks.add_task(_run_agent_background_with_id, site.id, agent_run.id)

    return AgentRunResponse(run_id=str(agent_run.id), status="running")


async def _run_agent_background_with_id(site_id: uuid.UUID, run_id: uuid.UUID):
    """Run LangGraph agent pipeline in background."""
    await run_agent_graph(site_id, run_id)


# Need Page import at module level
from app.models.page import Page


@router.get("/runs/{site_id}")
async def get_agent_runs(site_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get all agent runs for a site."""
    result = await db.execute(
        select(AgentRun)
        .where(AgentRun.site_id == site_id)
        .order_by(AgentRun.started_at.desc())
        .limit(20)
    )
    runs = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "status": r.status,
            "trigger": r.trigger,
            "pages_analyzed": r.pages_analyzed,
            "issues_found": r.issues_found,
            "summary": r.summary,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in runs
    ]


@router.get("/run/{run_id}")
async def get_agent_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get status of a specific agent run."""
    run = await db.get(AgentRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return {
        "id": str(run.id),
        "status": run.status,
        "trigger": run.trigger,
        "pages_analyzed": run.pages_analyzed,
        "issues_found": run.issues_found,
        "summary": run.summary,
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


@router.get("/issues/{site_id}")
async def get_issues(
    site_id: uuid.UUID,
    status: str = "open",
    category: str | None = None,
    severity: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Get issues for a site with optional filters."""
    query = select(Issue).where(Issue.site_id == site_id)

    if status != "all":
        query = query.where(Issue.status == status)
    if category:
        query = query.where(Issue.category == category)
    if severity:
        query = query.where(Issue.severity == severity)

    query = query.order_by(
        # Sort critical first
        case(
            (Issue.severity == "critical", 0),
            (Issue.severity == "high", 1),
            (Issue.severity == "medium", 2),
            (Issue.severity == "low", 3),
        ),
        Issue.created_at.desc(),
    )

    result = await db.execute(query)
    issues = result.scalars().all()

    return [
        {
            "id": str(i.id),
            "category": i.category,
            "severity": i.severity,
            "title": i.title,
            "description": i.description,
            "recommendation": i.recommendation,
            "affected_url": i.affected_url,
            "status": i.status,
            "created_at": i.created_at.isoformat() if i.created_at else None,
        }
        for i in issues
    ]


@router.patch("/issues/{issue_id}")
async def update_issue_status(
    issue_id: uuid.UUID,
    status: str,
    db: AsyncSession = Depends(get_db),
):
    """Dismiss or mark an issue as fixed."""
    if status not in ("open", "dismissed", "fixed"):
        raise HTTPException(status_code=422, detail="Status must be open, dismissed, or fixed")

    issue = await db.get(Issue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    issue.status = status
    await db.commit()
    return {"id": str(issue.id), "status": issue.status}


@router.get("/health-score/{site_id}")
async def get_health_score(site_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get SEO health score for a site."""
    site = await db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    return await calculate_health_score(db, site_id)


@router.get("/scheduler-status")
async def get_scheduler_status():
    """Get scheduler status and next run time."""
    from app.services.scheduler import scheduler
    jobs = scheduler.get_jobs()
    return {
        "running": scheduler.running,
        "jobs": [
            {
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            }
            for job in jobs
        ],
    }


@router.post("/trigger-scheduled-run")
async def trigger_scheduled_run(background_tasks: BackgroundTasks):
    """Manually trigger the scheduled agent run for all sites."""
    from app.services.scheduler import scheduled_agent_run
    background_tasks.add_task(scheduled_agent_run)
    return {"status": "triggered"}
