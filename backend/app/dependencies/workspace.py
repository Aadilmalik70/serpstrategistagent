from dataclasses import dataclass
import uuid

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.identity import Membership, User, Workspace


@dataclass(frozen=True)
class WorkspaceContext:
    user: User
    workspace: Workspace
    membership: Membership


async def get_current_workspace(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workspace_header: str | None = Header(default=None, alias="X-Workspace-ID"),
) -> WorkspaceContext:
    """Resolve an active workspace that the authenticated user belongs to."""
    workspace_id: uuid.UUID | None = None
    if workspace_header:
        try:
            workspace_id = uuid.UUID(workspace_header)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="X-Workspace-ID must be a valid UUID",
            ) from exc

    query = (
        select(Membership, Workspace)
        .join(Workspace, Workspace.id == Membership.workspace_id)
        .where(
            Membership.user_id == current_user.id,
            Membership.status == "active",
            Workspace.status == "active",
        )
    )
    if workspace_id:
        query = query.where(Workspace.id == workspace_id)
    else:
        query = query.order_by(Membership.joined_at.asc()).limit(1)

    row = (await db.execute(query)).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active workspace membership is available",
        )

    membership, workspace = row
    return WorkspaceContext(user=current_user, workspace=workspace, membership=membership)


def require_workspace_role(context: WorkspaceContext, *roles: str) -> None:
    if context.membership.role not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This workspace role cannot perform the requested action",
        )
