import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.models.issue import Issue
from app.models.operator_action import OperatorAction
from app.models.site import Site
from app.schemas.technical_finding import (
    FindingRefreshResponse,
    FindingStatusUpdate,
    TechnicalFindingQueueResponse,
    TechnicalFindingResponse,
)
from app.services.site_service import get_site_by_id
from app.services.technical_finding_service import (
    ACTIVE_FINDING_STATUSES,
    ensure_action_for_finding,
    run_technical_finding_pipeline,
)


router = APIRouter(prefix="/technical-findings", tags=["technical-findings"])


async def _require_site(
    db: AsyncSession,
    context: WorkspaceContext,
    site_id: uuid.UUID,
) -> Site:
    site = await get_site_by_id(db, site_id, context.workspace.id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


async def _require_finding(
    db: AsyncSession,
    context: WorkspaceContext,
    finding_id: uuid.UUID,
) -> Issue:
    finding = await db.scalar(
        select(Issue)
        .join(Site, Site.id == Issue.site_id)
        .where(Issue.id == finding_id, Site.workspace_id == context.workspace.id)
    )
    if not finding:
        raise HTTPException(status_code=404, detail="Technical finding not found")
    return finding


async def _latest_action(db: AsyncSession, workspace_id: uuid.UUID, finding_id: uuid.UUID) -> OperatorAction | None:
    return await db.scalar(
        select(OperatorAction)
        .where(
            OperatorAction.workspace_id == workspace_id,
            OperatorAction.issue_id == finding_id,
        )
        .order_by(OperatorAction.created_at.desc())
        .limit(1)
    )


def _response(finding: Issue, action: OperatorAction | None = None) -> TechnicalFindingResponse:
    execution_target = action.execution_target if action else {}
    proposed_diff = action.proposed_diff if action else {}
    planner = proposed_diff.get("planner") if isinstance(proposed_diff, dict) else {}
    if not isinstance(planner, dict):
        planner = {}
    return TechnicalFindingResponse(
        id=finding.id,
        site_id=finding.site_id,
        page_id=finding.page_id,
        agent_run_id=finding.agent_run_id,
        source_crawl_id=finding.source_crawl_id,
        finding_type=finding.finding_type,
        fingerprint=finding.fingerprint,
        detector_version=finding.detector_version,
        category=finding.category,
        severity=finding.severity,
        status=finding.status,
        title=finding.title,
        description=finding.description,
        recommendation=finding.recommendation,
        affected_url=finding.affected_url,
        affected_urls=list(finding.affected_urls or []),
        evidence=list(finding.evidence or []),
        impact_score=finding.impact_score,
        confidence_score=finding.confidence_score,
        effort_score=finding.effort_score,
        occurrence_count=finding.occurrence_count,
        regression_count=finding.regression_count,
        first_seen_at=finding.first_seen_at,
        last_seen_at=finding.last_seen_at,
        resolved_at=finding.resolved_at,
        action_id=action.id if action else None,
        action_status=action.status if action else None,
        action_adapter=(
            str(execution_target.get("adapter") or "").strip().lower() or None
            if isinstance(execution_target, dict)
            else None
        ),
        patch_status=str(planner.get("status") or "").strip().lower() or None,
        patch_reason=str(planner.get("reason") or "").strip() or None,
        patch_source_path=str(planner.get("source_path") or "").strip() or None,
    )


@router.get("/sites/{site_id}", response_model=TechnicalFindingQueueResponse)
async def list_technical_findings(
    site_id: uuid.UUID,
    status: str = Query(default="active"),
    severity: str | None = Query(default=None),
    finding_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> TechnicalFindingQueueResponse:
    await _require_site(db, context, site_id)
    query = select(Issue).where(Issue.site_id == site_id)
    if status == "active":
        query = query.where(Issue.status.in_(ACTIVE_FINDING_STATUSES))
    elif status != "all":
        query = query.where(Issue.status == status)
    if severity:
        query = query.where(Issue.severity == severity)
    if finding_type:
        query = query.where(Issue.finding_type == finding_type)
    query = query.order_by(
        case(
            (Issue.status == "regressed", 0),
            (Issue.severity == "critical", 1),
            (Issue.severity == "high", 2),
            (Issue.severity == "medium", 3),
            else_=4,
        ),
        Issue.impact_score.desc(),
        Issue.last_seen_at.desc(),
    ).limit(limit)
    findings = list((await db.execute(query)).scalars().all())

    counts_by_status = dict((await db.execute(
        select(Issue.status, func.count(Issue.id))
        .where(Issue.site_id == site_id)
        .group_by(Issue.status)
    )).all())
    counts_by_severity = dict((await db.execute(
        select(Issue.severity, func.count(Issue.id))
        .where(Issue.site_id == site_id, Issue.status.in_(ACTIVE_FINDING_STATUSES))
        .group_by(Issue.severity)
    )).all())

    items = []
    for finding in findings:
        action = await _latest_action(db, context.workspace.id, finding.id)
        items.append(_response(finding, action))
    return TechnicalFindingQueueResponse(
        items=items,
        total=sum(counts_by_status.values()),
        counts_by_status=counts_by_status,
        counts_by_severity=counts_by_severity,
    )


@router.post("/sites/{site_id}/refresh", response_model=FindingRefreshResponse)
async def refresh_technical_findings(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> FindingRefreshResponse:
    require_workspace_role(context, "owner", "admin")
    site = await _require_site(db, context, site_id)
    result = await run_technical_finding_pipeline(
        db,
        site=site,
        actor_user_id=context.user.id,
    )
    return FindingRefreshResponse(**result)


@router.post("/{finding_id}/action")
async def create_finding_action(
    finding_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    require_workspace_role(context, "owner", "admin")
    finding = await _require_finding(db, context, finding_id)
    if finding.status not in ACTIVE_FINDING_STATUSES:
        raise HTTPException(status_code=409, detail="Only active findings can create operator actions")
    action, created = await ensure_action_for_finding(
        db,
        workspace_id=context.workspace.id,
        finding=finding,
        actor_user_id=context.user.id,
    )
    if not action:
        raise HTTPException(status_code=422, detail="This finding does not have an executable action blueprint")
    return {"action_id": str(action.id), "status": action.status, "created": created}


@router.patch("/{finding_id}", response_model=TechnicalFindingResponse)
async def update_finding_status(
    finding_id: uuid.UUID,
    data: FindingStatusUpdate,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> TechnicalFindingResponse:
    require_workspace_role(context, "owner", "admin")
    finding = await _require_finding(db, context, finding_id)
    finding.status = data.status
    finding.resolved_at = None
    await db.commit()
    await db.refresh(finding)
    action = await _latest_action(db, context.workspace.id, finding.id)
    return _response(finding, action)
