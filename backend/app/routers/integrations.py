import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.schemas.integration import (
    IntegrationCredentialCreate,
    IntegrationCredentialResponse,
    IntegrationCredentialRotate,
    IntegrationCredentialTestResponse,
    IntegrationProviderDefinition,
)
from app.services.integration_service import (
    IntegrationServiceError,
    create_integration,
    list_integrations,
    provider_catalog,
    revoke_integration,
    rotate_integration,
    test_integration,
)

router = APIRouter(prefix="/integrations", tags=["integrations"])


def _service_error(exc: IntegrationServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("/providers", response_model=list[IntegrationProviderDefinition])
async def list_provider_catalog(
    context: WorkspaceContext = Depends(get_current_workspace),
) -> list[IntegrationProviderDefinition]:
    del context
    return provider_catalog()


@router.get("", response_model=list[IntegrationCredentialResponse])
async def list_workspace_integrations(
    site_id: uuid.UUID | None = Query(default=None),
    include_revoked: bool = Query(default=False),
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[IntegrationCredentialResponse]:
    return await list_integrations(
        db,
        workspace_id=context.workspace.id,
        site_id=site_id,
        include_revoked=include_revoked,
    )


@router.post("", response_model=IntegrationCredentialResponse, status_code=status.HTTP_201_CREATED)
async def connect_integration(
    data: IntegrationCredentialCreate,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> IntegrationCredentialResponse:
    require_workspace_role(context, "owner", "admin")
    try:
        return await create_integration(
            db,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            provider=data.provider,
            label=data.label,
            site_id=data.site_id,
            external_account_id=data.external_account_id,
            credentials=data.credentials,
        )
    except IntegrationServiceError as exc:
        raise _service_error(exc) from exc


@router.put("/{credential_id}", response_model=IntegrationCredentialResponse)
async def rotate_workspace_integration(
    credential_id: uuid.UUID,
    data: IntegrationCredentialRotate,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> IntegrationCredentialResponse:
    require_workspace_role(context, "owner", "admin")
    try:
        return await rotate_integration(
            db,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            credential_id=credential_id,
            label=data.label,
            credentials=data.credentials,
        )
    except IntegrationServiceError as exc:
        raise _service_error(exc) from exc


@router.post("/{credential_id}/test", response_model=IntegrationCredentialTestResponse)
async def test_workspace_integration(
    credential_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> IntegrationCredentialTestResponse:
    require_workspace_role(context, "owner", "admin")
    try:
        credential, message = await test_integration(
            db,
            workspace_id=context.workspace.id,
            credential_id=credential_id,
        )
    except IntegrationServiceError as exc:
        raise _service_error(exc) from exc

    if credential.last_validated_at is None:
        raise HTTPException(status_code=500, detail="Integration validation timestamp is unavailable")
    return IntegrationCredentialTestResponse(
        id=credential.id,
        provider=credential.provider,
        status=credential.last_validation_status,
        message=message,
        tested_at=credential.last_validated_at,
    )


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_workspace_integration(
    credential_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> Response:
    require_workspace_role(context, "owner", "admin")
    try:
        await revoke_integration(
            db,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            credential_id=credential_id,
        )
    except IntegrationServiceError as exc:
        raise _service_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
