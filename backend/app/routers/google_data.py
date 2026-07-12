from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.schemas.google_data import (
    GoogleDataConnectionResponse,
    GoogleOAuthStartResponse,
    GooglePropertyCatalogResponse,
    GooglePropertySelectionRequest,
)
from app.services.google_data_service import (
    GoogleDataServiceError,
    complete_google_oauth,
    connection_response,
    get_connection,
    list_google_properties,
    start_google_oauth,
)

router = APIRouter(prefix="/integrations/google-data", tags=["google-data"])
callback_router = APIRouter(tags=["google-data"])


def _service_error(exc: GoogleDataServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


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
    code: str = Query(min_length=1),
    state: str = Query(min_length=20),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    try:
        redirect_url = await complete_google_oauth(db, code, state)
    except GoogleDataServiceError as exc:
        raise _service_error(exc) from exc
    return RedirectResponse(redirect_url, status_code=303)


@router.get("/properties", response_model=GooglePropertyCatalogResponse)
async def google_data_properties(
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> GooglePropertyCatalogResponse:
    connection = await get_connection(db, context.workspace.id, context.user.id)
    if not connection or connection.status != "connected":
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
    if not connection or connection.status != "connected":
        raise HTTPException(status_code=409, detail="Connect Google data before selecting properties")

    try:
        gsc, ga4 = await list_google_properties(db, connection)
    except GoogleDataServiceError as exc:
        raise _service_error(exc) from exc

    allowed_gsc = {item.id for item in gsc}
    allowed_ga4 = {item.id: item.name for item in ga4}
    if data.gsc_property and data.gsc_property not in allowed_gsc:
        raise HTTPException(status_code=400, detail="Selected Search Console property is unavailable")
    if data.ga4_property_id and data.ga4_property_id not in allowed_ga4:
        raise HTTPException(status_code=400, detail="Selected GA4 property is unavailable")

    connection.gsc_property = data.gsc_property
    connection.ga4_property_id = data.ga4_property_id
    connection.ga4_property_name = (
        allowed_ga4.get(data.ga4_property_id)
        if data.ga4_property_id
        else None
    )
    connection.last_error = None
    await db.commit()
    await db.refresh(connection)
    return connection_response(connection)
