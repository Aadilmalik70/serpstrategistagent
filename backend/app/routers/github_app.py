import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.models.github_app import GitHubAppInstallation
from app.schemas.github_app import (
    GitHubAppRepositoryCatalog,
    GitHubAppRepositorySelectRequest,
    GitHubAppSiteStatus,
    GitHubAppStartRequest,
    GitHubAppStartResponse,
)
from app.services.github_app_service import (
    GitHubAppServiceError,
    complete_installation,
    github_app_configured,
    list_installation_repositories,
    select_repository,
    start_installation,
)
from app.services.site_service import get_site_by_id

router = APIRouter(prefix="/integrations/github-app", tags=["github-app"])
callback_router = APIRouter(tags=["github-app"])


def _service_error(exc: GitHubAppServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


def _onboarding_return(**params: str) -> str:
    base = f"{get_settings().frontend_url.rstrip('/')}/onboarding"
    return f"{base}?{urlencode({'step': 'cms', **params})}"


@router.get("/status/{site_id}", response_model=GitHubAppSiteStatus)
async def github_app_status(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> GitHubAppSiteStatus:
    site = await get_site_by_id(db, site_id, context.workspace.id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    installation = (
        await db.get(GitHubAppInstallation, site.github_app_installation_id)
        if site.github_app_installation_id
        else None
    )
    return GitHubAppSiteStatus(
        configured=github_app_configured(),
        installed=bool(installation and installation.status == "active"),
        site_id=site.id,
        repository=site.github_repo,
        installation_record_id=installation.id if installation else None,
        account_login=installation.account_login if installation else None,
        execution_ready=bool(installation and site.github_repo),
    )


@router.post("/start", response_model=GitHubAppStartResponse)
async def start_github_app_installation(
    data: GitHubAppStartRequest,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> GitHubAppStartResponse:
    require_workspace_role(context, "owner", "admin")
    try:
        installation_url = await start_installation(
            db,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            site_id=data.site_id,
        )
    except GitHubAppServiceError as exc:
        raise _service_error(exc) from exc
    return GitHubAppStartResponse(installation_url=installation_url)


@callback_router.get("/integrations/github-app/callback")
async def github_app_callback(
    installation_id: int | None = Query(default=None),
    setup_action: str | None = Query(default=None),
    state: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    if setup_action == "request":
        return RedirectResponse(_onboarding_return(github_error="installation_requested"), status_code=303)
    if setup_action == "delete":
        return RedirectResponse(_onboarding_return(github_error="installation_deleted"), status_code=303)
    if not installation_id or not state:
        return RedirectResponse(_onboarding_return(github_error="invalid_callback"), status_code=303)
    try:
        redirect_url = await complete_installation(
            db,
            installation_id=installation_id,
            state=state,
        )
    except GitHubAppServiceError as exc:
        return RedirectResponse(_onboarding_return(github_error=str(exc)[:120]), status_code=303)
    return RedirectResponse(redirect_url, status_code=303)


@router.get("/repositories", response_model=GitHubAppRepositoryCatalog)
async def github_app_repositories(
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> GitHubAppRepositoryCatalog:
    require_workspace_role(context, "owner", "admin")
    if not github_app_configured():
        return GitHubAppRepositoryCatalog(configured=False, repositories=[])
    try:
        repositories = await list_installation_repositories(
            db,
            workspace_id=context.workspace.id,
        )
    except GitHubAppServiceError as exc:
        raise _service_error(exc) from exc
    return GitHubAppRepositoryCatalog(configured=True, repositories=repositories)


@router.put("/repository", response_model=GitHubAppSiteStatus)
async def choose_github_repository(
    data: GitHubAppRepositorySelectRequest,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> GitHubAppSiteStatus:
    require_workspace_role(context, "owner", "admin")
    try:
        site = await select_repository(
            db,
            workspace_id=context.workspace.id,
            site_id=data.site_id,
            installation_record_id=data.installation_record_id,
            repository=data.repository,
        )
    except GitHubAppServiceError as exc:
        raise _service_error(exc) from exc
    installation = await db.get(GitHubAppInstallation, site.github_app_installation_id)
    return GitHubAppSiteStatus(
        configured=True,
        installed=True,
        site_id=site.id,
        repository=site.github_repo,
        installation_record_id=installation.id if installation else None,
        account_login=installation.account_login if installation else None,
        execution_ready=bool(installation and site.github_repo),
    )
