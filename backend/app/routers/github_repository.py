import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.models.github_app import GitHubAppInstallation, GitHubRepositoryConnection
from app.schemas.github_repository import GitHubRepositoryConnectRequest, GitHubRepositoryResponse
from app.services.github_app_service import GitHubAppError, connect_authorized_repository
from app.services.site_service import get_site_by_id

router = APIRouter(prefix="/integrations/github-repository", tags=["github-repository"])


def _execution_ready(installation: GitHubAppInstallation | None) -> bool:
    if installation is None or not get_settings().github_execution_enabled:
        return False
    permissions = installation.permissions or {}
    return (
        permissions.get("contents") == "write"
        and permissions.get("pull_requests") == "write"
    )


@router.get("/{site_id}", response_model=GitHubRepositoryResponse)
async def github_repository_status(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> GitHubRepositoryResponse:
    site = await get_site_by_id(db, site_id, context.workspace.id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    connection = await db.scalar(
        select(GitHubRepositoryConnection).where(
            GitHubRepositoryConnection.site_id == site.id,
            GitHubRepositoryConnection.workspace_id == context.workspace.id,
            GitHubRepositoryConnection.status == "active",
        )
    )
    installation = (
        await db.scalar(
            select(GitHubAppInstallation).where(
                GitHubAppInstallation.id == connection.installation_id,
                GitHubAppInstallation.workspace_id == context.workspace.id,
                GitHubAppInstallation.status == "active",
            )
        )
        if connection and connection.installation_id
        else None
    )
    return GitHubRepositoryResponse(
        site_id=site.id,
        repository=connection.repository_full_name if connection else site.github_repo,
        connected=bool(connection or site.github_repo),
        visibility=connection.visibility if connection else ("public" if site.github_repo else None),
        default_branch=connection.default_branch if connection else None,
        installation_id=installation.id if installation else None,
        repository_id=connection.github_repository_id if connection else None,
        authorization_source="github_app" if installation else "public",
        authorization_ready=bool(installation),
        execution_ready=_execution_ready(installation),
    )


@router.post("", response_model=GitHubRepositoryResponse)
async def connect_github_repository(
    data: GitHubRepositoryConnectRequest,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> GitHubRepositoryResponse:
    require_workspace_role(context, "owner", "admin")
    site = await get_site_by_id(db, data.site_id, context.workspace.id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    if data.installation_id and data.repository_id:
        try:
            connection = await connect_authorized_repository(
                db,
                workspace_id=context.workspace.id,
                site_id=site.id,
                installation_record_id=data.installation_id,
                repository_id=data.repository_id,
            )
        except GitHubAppError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": str(exc), "retryable": exc.retryable},
            ) from exc
        return GitHubRepositoryResponse(
            site_id=site.id,
            repository=connection.repository_full_name,
            connected=True,
            visibility=connection.visibility,
            default_branch=connection.default_branch,
            installation_id=connection.installation_id,
            repository_id=connection.github_repository_id,
            authorization_source="github_app",
            authorization_ready=True,
            execution_ready=_execution_ready(
                await db.get(GitHubAppInstallation, connection.installation_id)
                if connection.installation_id
                else None
            ),
        )

    if not data.repository:
        raise HTTPException(status_code=422, detail="A public repository is required")

    settings = get_settings()
    try:
        async with httpx.AsyncClient(
            timeout=settings.github_app_timeout_seconds,
            follow_redirects=False,
        ) as client:
            response = await client.get(
                f"{settings.github_api_url}/repos/{data.repository}",
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "SERP-Strategists-Onboarding",
                },
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail="GitHub repository verification is temporarily unavailable",
        ) from exc
    if response.status_code == 404:
        raise HTTPException(
            status_code=404,
            detail="Repository was not found or is private. Private repositories require the GitHub App connector.",
        )
    if response.status_code == 403:
        raise HTTPException(status_code=503, detail="GitHub repository verification is temporarily rate limited")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="GitHub repository could not be verified")

    repository = response.json()
    if repository.get("private"):
        raise HTTPException(status_code=400, detail="Private repositories require the GitHub App connector")

    full_name = repository.get("full_name") or data.repository
    connection = await db.scalar(
        select(GitHubRepositoryConnection).where(
            GitHubRepositoryConnection.site_id == site.id
        )
    )
    if connection is None:
        connection = GitHubRepositoryConnection(
            workspace_id=context.workspace.id,
            site_id=site.id,
            repository_full_name=str(full_name),
        )
        db.add(connection)
    connection.workspace_id = context.workspace.id
    connection.installation_id = None
    connection.github_repository_id = int(repository["id"]) if repository.get("id") else None
    connection.repository_full_name = str(full_name)[:255]
    connection.visibility = "public"
    connection.default_branch = (
        str(repository.get("default_branch"))[:255]
        if repository.get("default_branch")
        else None
    )
    connection.permissions = {}
    connection.status = "active"
    site.github_repo = full_name
    site.cms = "github"
    await db.commit()
    await db.refresh(site)
    return GitHubRepositoryResponse(
        site_id=site.id,
        repository=site.github_repo,
        connected=True,
        visibility="public",
        default_branch=repository.get("default_branch"),
        repository_id=connection.github_repository_id,
        authorization_source="public",
        authorization_ready=False,
        execution_ready=False,
    )


@router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_github_repository(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> Response:
    require_workspace_role(context, "owner", "admin")
    site = await get_site_by_id(db, site_id, context.workspace.id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    connection = await db.scalar(
        select(GitHubRepositoryConnection).where(
            GitHubRepositoryConnection.site_id == site.id,
            GitHubRepositoryConnection.workspace_id == context.workspace.id,
        )
    )
    if connection:
        connection.status = "revoked"
    site.github_repo = None
    if site.cms == "github":
        site.cms = None
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
