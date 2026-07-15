import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.models.agent_run import AgentRun
from app.models.issue import Issue
from app.models.job_queue import JobQueue
from app.models.site import Site
from app.services.crawl_job_service import ACTIVE_CRAWL_STATUSES, enqueue_crawl_job
from app.services.health_score import calculate_health_score
from app.services.site_service import get_site_by_id

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentRunRequest(BaseModel):
    site_id: uuid.UUID


class AgentRunResponse(BaseModel):
    run_id: str
    status: str


async def _require_site(
    db: AsyncSession,
    context: WorkspaceContext,
    site_id: uuid.UUID,
) -> Site:
    site = await get_site_by_id(db, site_id, context.workspace.id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


@router.post("/run", response_model=AgentRunResponse, status_code=202)
async def start_agent_run(
    data: AgentRunRequest,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> AgentRunResponse:
    require_workspace_role(context, "owner", "admin")
    site = await _require_site(db, context, data.site_id)

    active_run = await db.scalar(
        select(AgentRun)
        .where(
            AgentRun.site_id == site.id,
            AgentRun.status.in_(["crawling", "running"]),
        )
        .order_by(AgentRun.started_at.desc())
    )
    if active_run:
        return AgentRunResponse(run_id=str(active_run.id), status=active_run.status)

    active_crawl = await db.scalar(
        select(JobQueue)
        .where(
            JobQueue.site_id == site.id,
            JobQueue.job_type == "crawl",
            JobQueue.status.in_(ACTIVE_CRAWL_STATUSES),
        )
        .order_by(JobQueue.created_at.desc())
    )

    if active_crawl:
        max_pages = int((active_crawl.payload or {}).get("max_pages") or 100)
    else:
        max_pages = 100

    agent_run = AgentRun(
        site_id=site.id,
        status="crawling",
        trigger="manual",
        summary="Crawling the site before analysis.",
        meta={"phase": "crawl"},
    )
    db.add(agent_run)
    await db.flush()
    if active_crawl:
        active_crawl.payload = {
            **(active_crawl.payload or {}),
            "agent_run_id": str(agent_run.id),
        }
        crawl_job = active_crawl
        await db.commit()
    else:
        crawl_job, _ = await enqueue_crawl_job(
            db,
            workspace_id=context.workspace.id,
            site=site,
            max_pages=max_pages,
            source="agent",
            agent_run_id=agent_run.id,
            priority=10,
        )
    await db.refresh(crawl_job)
    await db.refresh(agent_run)
    agent_run.meta = {"phase": "crawl", "crawl_job_id": str(crawl_job.id)}
    await db.commit()

    return AgentRunResponse(run_id=str(agent_run.id), status="crawling")


@router.get("/runs/{site_id}")
async def get_agent_runs(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    await _require_site(db, context, site_id)
    runs = (
        await db.execute(
            select(AgentRun)
            .where(AgentRun.site_id == site_id)
            .order_by(AgentRun.started_at.desc())
            .limit(20)
        )
    ).scalars().all()
    return [
        {
            "id": str(run.id),
            "status": run.status,
            "trigger": run.trigger,
            "pages_analyzed": run.pages_analyzed,
            "issues_found": run.issues_found,
            "summary": run.summary,
            "error": run.error,
            "meta": run.meta or {},
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }
        for run in runs
    ]


@router.get("/run/{run_id}")
async def get_agent_run(
    run_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    run = (
        await db.execute(
            select(AgentRun)
            .join(Site, Site.id == AgentRun.site_id)
            .where(AgentRun.id == run_id, Site.workspace_id == context.workspace.id)
        )
    ).scalar_one_or_none()
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
        "meta": run.meta or {},
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


@router.get("/issues/{site_id}")
async def get_issues(
    site_id: uuid.UUID,
    status: str = "open",
    category: str | None = None,
    severity: str | None = None,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    await _require_site(db, context, site_id)
    query = select(Issue).where(Issue.site_id == site_id)
    if status in {"active", "open"}:
        query = query.where(Issue.status.in_(["open", "regressed"]))
    elif status != "all":
        query = query.where(Issue.status == status)
    if category:
        query = query.where(Issue.category == category)
    if severity:
        query = query.where(Issue.severity == severity)

    query = query.order_by(
        case(
            (Issue.severity == "critical", 0),
            (Issue.severity == "high", 1),
            (Issue.severity == "medium", 2),
            (Issue.severity == "low", 3),
        ),
        Issue.created_at.desc(),
    )
    issues = (await db.execute(query)).scalars().all()
    return [
        {
            "id": str(issue.id),
            "finding_type": issue.finding_type,
            "fingerprint": issue.fingerprint,
            "detector_version": issue.detector_version,
            "category": issue.category,
            "severity": issue.severity,
            "title": issue.title,
            "description": issue.description,
            "recommendation": issue.recommendation,
            "affected_url": issue.affected_url,
            "affected_urls": issue.affected_urls or [],
            "evidence": issue.evidence or [],
            "impact_score": issue.impact_score,
            "confidence_score": issue.confidence_score,
            "effort_score": issue.effort_score,
            "occurrence_count": issue.occurrence_count,
            "regression_count": issue.regression_count,
            "status": issue.status,
            "created_at": issue.created_at.isoformat() if issue.created_at else None,
        }
        for issue in issues
    ]


@router.patch("/issues/{issue_id}")
async def update_issue_status(
    issue_id: uuid.UUID,
    status: str,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    require_workspace_role(context, "owner", "admin")
    if status not in ("open", "dismissed"):
        raise HTTPException(status_code=422, detail="Status must be open or dismissed")

    issue = (
        await db.execute(
            select(Issue)
            .join(Site, Site.id == Issue.site_id)
            .where(Issue.id == issue_id, Site.workspace_id == context.workspace.id)
        )
    ).scalar_one_or_none()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    issue.status = status
    await db.commit()
    return {"id": str(issue.id), "status": issue.status}


@router.get("/health-score/{site_id}")
async def get_health_score(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    await _require_site(db, context, site_id)
    return await calculate_health_score(db, site_id)


@router.get("/scheduler-status")
async def get_scheduler_status(
    context: WorkspaceContext = Depends(get_current_workspace),
):
    from app.services.scheduler import scheduler

    return {
        "running": scheduler.running,
        "workspace_id": str(context.workspace.id),
        "jobs": [],
    }


@router.post("/trigger-scheduled-run", status_code=410)
async def trigger_scheduled_run(
    context: WorkspaceContext = Depends(get_current_workspace),
):
    require_workspace_role(context, "owner", "admin")
    raise HTTPException(
        status_code=410,
        detail="Global scheduled execution is disabled until durable workspace-scoped jobs are implemented",
    )
