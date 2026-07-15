import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.models.github_app import GitHubAppInstallation
from app.schemas.github_app import (
    GitHubAppInstallationResponse,
    GitHubAppStartResponse,
    GitHubAppStatusResponse,
    GitHubAuthorizedRepositoryListResponse,
    GitHubAuthorizedRepositoryResponse,
)
from app.services.github_app_service import (
    GitHubAppError,
    complete_installation,
    create_install_intent,
    disconnect_installation,
    github_app_configured,
    workspace_installations,
    workspace_repositories,
)


router = APIRouter(prefix="/integrations/github-app", tags=["github-app"])
settings = get_settings()


def _installation_response(item: GitHubAppInstallation) -> GitHubAppInstallationResponse:
    return GitHubAppInstallationResponse(
        id=item.id,
        installation_id=item.installation_id,
        account_login=item.account_login,
        account_type=item.account_type,
        repository_selection=item.repository_selection,
        permissions=item.permissions or {},
        status=item.status,
        last_verified_at=item.last_verified_at,
        created_at=item.created_at,
    )


def _error(exc: GitHubAppError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc), "retryable": exc.retryable},
    )


def _settings_redirect(**params: str) -> str:
    return f"{settings.frontend_url.rstrip('/')}/settings/integrations?{urlencode(params)}"


@router.get("/status", response_model=GitHubAppStatusResponse)
async def github_app_status(
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> GitHubAppStatusResponse:
    installations = await workspace_installations(db, workspace_id=context.workspace.id)
    return GitHubAppStatusResponse(
        configured=github_app_configured(),
        connected=any(item.status == "active" for item in installations),
        execution_enabled=False,
        installations=[_installation_response(item) for item in installations],
    )


@router.post("/start", response_model=GitHubAppStartResponse)
async def start_github_app_installation(
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> GitHubAppStartResponse:
    require_workspace_role(context, "owner", "admin")
    try:
        installation_url = await create_install_intent(
            db,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
        )
    except GitHubAppError as exc:
        raise _error(exc) from exc
    return GitHubAppStartResponse(installation_url=installation_url)


@router.get("/callback", include_in_schema=False)
async def github_app_callback(
    installation_id: int | None = Query(default=None, gt=0),
    setup_action: str | None = Query(default=None),
    state: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    if not installation_id or not state or setup_action not in {"install", "update"}:
        return RedirectResponse(
            _settings_redirect(github_app_error="invalid_callback"),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    try:
        await complete_installation(db, state=state, installation_id=installation_id)
    except GitHubAppError as exc:
        await db.rollback()
        return RedirectResponse(
            _settings_redirect(github_app_error=exc.code),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(
        _settings_redirect(github_app="connected"),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/repositories", response_model=GitHubAuthorizedRepositoryListResponse)
async def list_authorized_repositories(
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> GitHubAuthorizedRepositoryListResponse:
    try:
        repositories = await workspace_repositories(db, workspace_id=context.workspace.id)
    except GitHubAppError as exc:
        raise _error(exc) from exc
    items: list[GitHubAuthorizedRepositoryResponse] = []
    for installation, repository in repositories:
        repository_id = repository.get("id")
        full_name = repository.get("full_name")
        if not isinstance(repository_id, int) or not isinstance(full_name, str):
            continue
        items.append(
            GitHubAuthorizedRepositoryResponse(
                installation_id=installation.id,
                repository_id=repository_id,
                full_name=full_name,
                private=bool(repository.get("private")),
                visibility=str(
                    repository.get("visibility")
                    or ("private" if repository.get("private") else "public")
                ),
                default_branch=(
                    str(repository.get("default_branch"))
                    if repository.get("default_branch")
                    else None
                ),
                permissions=(
                    repository.get("permissions")
                    if isinstance(repository.get("permissions"), dict)
                    else {}
                ),
            )
        )
    return GitHubAuthorizedRepositoryListResponse(items=items, total=len(items))


@router.delete("/{installation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_github_app_installation(
    installation_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> Response:
    require_workspace_role(context, "owner", "admin")
    try:
        await disconnect_installation(
            db,
            workspace_id=context.workspace.id,
            installation_record_id=installation_id,
        )
    except GitHubAppError as exc:
        raise _error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
