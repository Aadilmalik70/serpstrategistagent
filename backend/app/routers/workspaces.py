from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.identity import User
from app.schemas.auth import WorkspaceCreateRequest, WorkspaceSummary
from app.services.auth_service import create_workspace_for_user, list_user_workspaces, workspace_summary

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceSummary])
async def list_workspaces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WorkspaceSummary]:
    return await list_user_workspaces(db, current_user.id)


@router.post("", response_model=WorkspaceSummary, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    data: WorkspaceCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceSummary:
    workspace, membership = await create_workspace_for_user(db, current_user, data.name)
    return workspace_summary(workspace, membership)
