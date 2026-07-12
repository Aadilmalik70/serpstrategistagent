import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.schemas.github_repository import GitHubRepositoryConnectRequest, GitHubRepositoryResponse
from app.services.site_service import get_site_by_id

router = APIRouter(prefix="/integrations/github-repository", tags=["github-repository"])


@router.get("/{site_id}", response_model=GitHubRepositoryResponse)
async def github_repository_status(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> GitHubRepositoryResponse:
    site = await get_site_by_id(db, site_id, context.workspace.id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return GitHubRepositoryResponse(
        site_id=site.id,
        repository=site.github_repo,
        connected=bool(site.github_repo),
        visibility="public" if site.github_repo else None,
        execution_ready=False,
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

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
        response = await client.get(
            f"https://api.github.com/repos/{data.repository}",
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "SERP-Strategists-Onboarding",
            },
        )
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
    site.github_repo = None
    if site.cms == "github":
        site.cms = None
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
