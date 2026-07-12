import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.models.agent_run import AgentRun
from app.models.issue import Issue
from app.models.site import Site
from app.services.agent_graph import run_agent_graph
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


@router.post("/run", response_model=AgentRunResponse)
async def start_agent_run(
    data: AgentRunRequest,
    background_tasks: BackgroundTasks,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    require_workspace_role(context, "owner", "admin")
    site = await _require_site(db, context, data.site_id)

    agent_run = AgentRun(site_id=site.id, status="running", trigger="manual")
    db.add(agent_run)
    await db.commit()
    await db.refresh(agent_run)
    background_tasks.add_task(_run_agent_background_with_id, site.id, agent_run.id)
    return AgentRunResponse(run_id=str(agent_run.id), status="running")


async def _run_agent_background_with_id(site_id: uuid.UUID, run_id: uuid.UUID):
    await run_agent_graph(site_id, run_id)


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
    if status != "all":
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
            "category": issue.category,
            "severity": issue.severity,
            "title": issue.title,
            "description": issue.description,
            "recommendation": issue.recommendation,
            "affected_url": issue.affected_url,
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
    if status not in ("open", "dismissed", "fixed"):
        raise HTTPException(status_code=422, detail="Status must be open, dismissed, or fixed")

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
