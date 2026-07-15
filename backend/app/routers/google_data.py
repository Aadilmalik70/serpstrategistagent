import logging
import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.schemas.google_data import (
    GoogleDataConnectionResponse,
    GoogleOAuthStartResponse,
    GooglePropertyCatalogResponse,
    GooglePropertySelectionRequest,
    SearchOpportunityListResponse,
    SearchOpportunityResponse,
    SearchSyncJobResponse,
)
from app.models.job_queue import JobQueue
from app.models.search_performance import SearchOpportunity
from app.models.site import Site
from app.services.credential_vault import CredentialVaultError
from app.services.google_baseline_service import sync_google_baseline
from app.services.google_data_service import (
    GoogleDataServiceError,
    complete_google_oauth,
    connection_response,
    get_connection,
    list_google_properties,
    start_google_oauth,
)
from app.services.search_performance_service import (
    SearchPerformanceError,
    enqueue_search_sync,
    reconcile_search_opportunities,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/google-data", tags=["google-data"])
callback_router = APIRouter(tags=["google-data"])


def _service_error(exc: GoogleDataServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


def _search_error(exc: SearchPerformanceError) -> HTTPException:
    headers = (
        {"Retry-After": str(exc.retry_after_seconds)}
        if exc.retry_after_seconds is not None
        else None
    )
    return HTTPException(status_code=exc.status_code, detail=str(exc), headers=headers)


def _job_response(job: JobQueue, *, reused: bool = False) -> SearchSyncJobResponse:
    return SearchSyncJobResponse(
        id=job.id,
        site_id=job.site_id,
        status=job.status,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        reused=reused,
        result=job.result,
        error_code=job.error_code,
        error_message=job.error_message,
        run_after=job.run_after,
        started_at=job.started_at,
        heartbeat_at=job.heartbeat_at,
        cancellation_requested=job.cancellation_requested,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


def _opportunity_response(item: SearchOpportunity) -> SearchOpportunityResponse:
    return SearchOpportunityResponse(
        id=str(item.id),
        site_id=str(item.site_id),
        opportunity_type=item.opportunity_type,
        status=item.status,
        title=item.title,
        query=item.query,
        page_url=item.page_url,
        priority_score=item.priority_score,
        confidence_score=item.confidence_score,
        metrics=item.metrics or {},
        evidence=item.evidence or [],
        first_detected_at=item.first_detected_at,
        last_detected_at=item.last_detected_at,
        resolved_at=item.resolved_at,
    )


def _onboarding_return(**params: str) -> str:
    base = f"{get_settings().frontend_url.rstrip('/')}/onboarding"
    return f"{base}?{urlencode({'step': 'google', **params})}"


@router.get("/status", response_model=GoogleDataConnectionResponse)
async def google_data_status(
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> GoogleDataConnectionResponse:
    connection = await get_connection(db, context.workspace.id, context.user.id)
    return connection_response(connection)


@router.post("/start", response_model=GoogleOAuthStartResponse)
async def start_google_data_connection(
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> GoogleOAuthStartResponse:
    require_workspace_role(context, "owner", "admin")
    try:
        authorization_url = await start_google_oauth(
            db,
            context.workspace.id,
            context.user.id,
        )
    except GoogleDataServiceError as exc:
        raise _service_error(exc) from exc
    return GoogleOAuthStartResponse(authorization_url=authorization_url)


@callback_router.get("/integrations/google/callback")
async def google_data_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    if error:
        return RedirectResponse(
            _onboarding_return(google_error="authorization_denied"),
            status_code=303,
        )
    if not code or not state:
        return RedirectResponse(
            _onboarding_return(google_error="invalid_callback"),
            status_code=303,
        )
    try:
        redirect_url = await complete_google_oauth(db, code, state)
    except CredentialVaultError:
        logger.exception("Google OAuth callback could not access the credential encryption vault")
        return RedirectResponse(
            _onboarding_return(google_error="credential_encryption_unavailable"),
            status_code=303,
        )
    except GoogleDataServiceError as exc:
        logger.warning("Google OAuth callback failed: %s", exc)
        return RedirectResponse(
            _onboarding_return(google_error="google_connection_failed"),
            status_code=303,
        )
    except Exception:
        logger.exception("Unexpected Google OAuth callback failure")
        return RedirectResponse(
            _onboarding_return(google_error="internal_error"),
            status_code=303,
        )
    return RedirectResponse(redirect_url, status_code=303)


@router.get("/properties", response_model=GooglePropertyCatalogResponse)
async def google_data_properties(
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> GooglePropertyCatalogResponse:
    connection = await get_connection(db, context.workspace.id, context.user.id)
    if not connection or connection.status not in {"connected", "configured"}:
        raise HTTPException(status_code=409, detail="Connect Google data before selecting properties")
    try:
        gsc, ga4 = await list_google_properties(db, connection)
    except GoogleDataServiceError as exc:
        raise _service_error(exc) from exc
    return GooglePropertyCatalogResponse(gsc_properties=gsc, ga4_properties=ga4)


@router.put("/properties", response_model=GoogleDataConnectionResponse)
async def select_google_data_properties(
    data: GooglePropertySelectionRequest,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> GoogleDataConnectionResponse:
    require_workspace_role(context, "owner", "admin")
    connection = await get_connection(db, context.workspace.id, context.user.id)
    if not connection or connection.status not in {"connected", "configured"}:
        raise HTTPException(status_code=409, detail="Connect Google data before selecting properties")
    if not data.gsc_property and not data.ga4_property_id:
        raise HTTPException(status_code=400, detail="Choose at least one Google property")

    try:
        gsc, ga4 = await list_google_properties(db, connection)
    except GoogleDataServiceError as exc:
        raise _service_error(exc) from exc

    allowed_gsc = {item.id for item in gsc}
    allowed_ga4 = {item.id: item.name for item in ga4}
    if data.gsc_property and data.gsc_property not in allowed_gsc:
        raise HTTPException(status_code=403, detail="Selected Search Console property is unavailable")
    if data.ga4_property_id and data.ga4_property_id not in allowed_ga4:
        raise HTTPException(status_code=403, detail="Selected GA4 property is unavailable")

    connection.gsc_property = data.gsc_property
    connection.ga4_property_id = data.ga4_property_id
    connection.ga4_property_name = allowed_ga4.get(data.ga4_property_id or "") or data.ga4_property_name
    connection.status = "configured"
    connection.baseline_status = "not_started"
    connection.baseline_summary = {}
    connection.last_synced_at = None
    connection.last_error = None
    await db.commit()
    await db.refresh(connection)
    return connection_response(connection)


@router.post("/sync", response_model=GoogleDataConnectionResponse)
async def sync_google_data(
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> GoogleDataConnectionResponse:
    require_workspace_role(context, "owner", "admin")
    connection = await get_connection(db, context.workspace.id, context.user.id)
    if not connection:
        raise HTTPException(status_code=409, detail="Connect Google data before synchronizing")
    try:
        synced = await sync_google_baseline(db, connection)
    except GoogleDataServiceError as exc:
        raise _service_error(exc) from exc
    return connection_response(synced)


@router.post(
    "/search-sync/{site_id}",
    response_model=SearchSyncJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_search_analytics_sync(
    site_id: uuid.UUID,
    response: Response,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> SearchSyncJobResponse:
    require_workspace_role(context, "owner", "admin")
    try:
        job, reused = await enqueue_search_sync(
            db,
            workspace_id=context.workspace.id,
            site_id=site_id,
        )
    except SearchPerformanceError as exc:
        raise _search_error(exc) from exc
    response.status_code = (
        status.HTTP_200_OK
        if reused and job.status == "completed"
        else status.HTTP_202_ACCEPTED
    )
    return _job_response(job, reused=reused)


@router.get(
    "/search-sync/sites/{site_id}/latest",
    response_model=SearchSyncJobResponse | None,
)
async def latest_search_analytics_sync(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> SearchSyncJobResponse | None:
    site = await db.scalar(
        select(Site).where(Site.id == site_id, Site.workspace_id == context.workspace.id)
    )
    if not site:
        raise HTTPException(status_code=404, detail="Site not found in this workspace")
    job = await db.scalar(
        select(JobQueue)
        .where(JobQueue.site_id == site_id, JobQueue.job_type == "gsc_search_sync")
        .order_by(JobQueue.created_at.desc(), JobQueue.id.desc())
        .limit(1)
    )
    return _job_response(job) if job else None


@router.get("/search-sync/jobs/{job_id}", response_model=SearchSyncJobResponse)
async def search_analytics_sync_status(
    job_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> SearchSyncJobResponse:
    job = await db.scalar(
        select(JobQueue)
        .join(Site, Site.id == JobQueue.site_id)
        .where(
            JobQueue.id == job_id,
            JobQueue.job_type == "gsc_search_sync",
            Site.workspace_id == context.workspace.id,
        )
    )
    if not job:
        raise HTTPException(status_code=404, detail="Search sync job not found")
    return _job_response(job)


@router.get("/opportunities/{site_id}", response_model=SearchOpportunityListResponse)
async def list_search_opportunities(
    site_id: uuid.UUID,
    include_resolved: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> SearchOpportunityListResponse:
    site = await db.scalar(
        select(Site).where(Site.id == site_id, Site.workspace_id == context.workspace.id)
    )
    if not site:
        raise HTTPException(status_code=404, detail="Site not found in this workspace")
    statement = select(SearchOpportunity).where(
        SearchOpportunity.workspace_id == context.workspace.id,
        SearchOpportunity.site_id == site_id,
    )
    if not include_resolved:
        statement = statement.where(SearchOpportunity.status == "active")
    total = int(
        await db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    )
    items = list(
        (
            await db.execute(
                statement.order_by(
                    SearchOpportunity.priority_score.desc(),
                    SearchOpportunity.last_detected_at.desc(),
                    SearchOpportunity.id.asc(),
                )
                .limit(limit)
            )
        ).scalars().all()
    )
    return SearchOpportunityListResponse(
        items=[_opportunity_response(item) for item in items],
        total=total,
    )


@router.post("/opportunities/{site_id}/detect", response_model=SearchOpportunityListResponse)
async def detect_search_opportunities(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> SearchOpportunityListResponse:
    require_workspace_role(context, "owner", "admin")
    site = await db.scalar(
        select(Site).where(Site.id == site_id, Site.workspace_id == context.workspace.id)
    )
    if not site:
        raise HTTPException(status_code=404, detail="Site not found in this workspace")
    items = await reconcile_search_opportunities(
        db,
        workspace_id=context.workspace.id,
        site_id=site_id,
    )
    await db.commit()
    ordered = sorted(
        items,
        key=lambda item: (-item.priority_score, -item.last_detected_at.timestamp(), str(item.id)),
    )
    return SearchOpportunityListResponse(
        items=[_opportunity_response(item) for item in ordered[:100]],
        total=len(ordered),
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_google_data(
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> Response:
    require_workspace_role(context, "owner", "admin")
    connection = await get_connection(db, context.workspace.id, context.user.id)
    if connection:
        connection.encrypted_tokens = None
        connection.token_fingerprint = None
        connection.oauth_state_hash = None
        connection.oauth_state_expires_at = None
        connection.status = "not_connected"
        connection.google_email = None
        connection.scopes = []
        connection.gsc_property = None
        connection.ga4_property_id = None
        connection.ga4_property_name = None
        connection.baseline_status = "not_started"
        connection.baseline_summary = {}
        connection.last_synced_at = None
        connection.last_error = None
        connection.connected_at = None
        connection.last_refreshed_at = None
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
