from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.models.free_audit import FreeAuditRequest
from app.models.job_queue import JobQueue
from app.models.site import Site
from app.routers.crawl import CrawlRequest, start_crawl
from app.schemas.free_audit import FreeAuditClaimResponse, FreeAuditCreate, FreeAuditResponse
from app.services.entitlement_service import assert_resource_quota
from app.services.free_audit_service import (
    FreeAuditServiceError,
    audit_response,
    create_free_audit,
    execute_free_audit,
    get_free_audit,
    requester_fingerprint,
)
from app.services.site_service import get_site_by_domain

router = APIRouter(prefix="/public/audits", tags=["public-audits"])


def _request_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else None


def _validate_token(token: str) -> None:
    if len(token) < 20 or len(token) > 64:
        raise HTTPException(status_code=404, detail="Audit not found")


@router.post("", response_model=FreeAuditResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_free_audit(
    data: FreeAuditCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> FreeAuditResponse:
    try:
        audit = await create_free_audit(
            db,
            data,
            requester_hash=requester_fingerprint(_request_ip(request)),
            user_agent=request.headers.get("user-agent"),
        )
    except FreeAuditServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if audit.status in {"queued", "failed"}:
        background_tasks.add_task(execute_free_audit, audit.id)
    return audit_response(audit)


@router.get("/{token}", response_model=FreeAuditResponse)
async def read_free_audit(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> FreeAuditResponse:
    _validate_token(token)
    audit = await get_free_audit(db, token)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")
    return audit_response(audit)


@router.post(
    "/{token}/claim",
    response_model=FreeAuditClaimResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def claim_free_audit(
    token: str,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> FreeAuditClaimResponse:
    """Claim a completed public audit and start one idempotent first-party crawl."""
    _validate_token(token)
    require_workspace_role(context, "owner", "admin")

    audit = await db.scalar(
        select(FreeAuditRequest)
        .where(FreeAuditRequest.public_token == token)
        .with_for_update()
    )
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")
    if audit.status != "completed":
        raise HTTPException(status_code=409, detail="The free audit must complete before it can be claimed")
    if audit.claimed_workspace_id and audit.claimed_workspace_id != context.workspace.id:
        raise HTTPException(status_code=409, detail="This audit has already been claimed")

    first_claim = audit.claimed_workspace_id is None
    site: Site | None = None
    if audit.claimed_site_id:
        site = await db.get(Site, audit.claimed_site_id)
    if site is None:
        site = await get_site_by_domain(db, audit.domain)

    reused_site = site is not None
    if site:
        if site.workspace_id != context.workspace.id:
            raise HTTPException(status_code=409, detail="This site is already assigned to another workspace")
    else:
        current_sites = int(
            await db.scalar(
                select(func.count(Site.id)).where(Site.workspace_id == context.workspace.id)
            )
            or 0
        )
        await assert_resource_quota(
            db,
            workspace_id=context.workspace.id,
            metric="sites",
            current=current_sites,
        )
        site = Site(
            domain=audit.domain,
            name=audit.domain,
            workspace_id=context.workspace.id,
            status="pending",
        )
        db.add(site)
        await db.flush()

    audit.claimed_by_user_id = audit.claimed_by_user_id or context.user.id
    audit.claimed_workspace_id = context.workspace.id
    audit.claimed_site_id = site.id
    audit.claimed_at = audit.claimed_at or datetime.now(timezone.utc)

    if not first_claim:
        existing_job = await db.scalar(
            select(JobQueue)
            .where(JobQueue.site_id == site.id, JobQueue.job_type == "crawl")
            .order_by(JobQueue.created_at.desc())
        )
        if existing_job:
            await db.commit()
            return FreeAuditClaimResponse(
                site_id=site.id,
                domain=site.domain,
                crawl_job_id=existing_job.id,
                crawl_status=existing_job.status,
                reused_site=True,
                reused_crawl=True,
                claimed_at=audit.claimed_at,
            )

    crawl = await start_crawl(
        data=CrawlRequest(site_id=site.id),
        context=context,
        db=db,
    )
    # start_crawl returns early for an active crawl, so commit the claim explicitly.
    await db.commit()
    return FreeAuditClaimResponse(
        site_id=site.id,
        domain=site.domain,
        crawl_job_id=crawl.job_id,
        crawl_status=crawl.status,
        reused_site=reused_site,
        reused_crawl=crawl.reused,
        claimed_at=audit.claimed_at,
    )
