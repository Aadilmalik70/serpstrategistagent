import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.models.identity import Membership, User, WorkspaceInvitation
from app.schemas.auth import (
    MembershipRoleUpdateRequest,
    WorkspaceCreateRequest,
    WorkspaceInvitationAcceptRequest,
    WorkspaceInvitationCreateRequest,
    WorkspaceInvitationCreated,
    WorkspaceInvitationSummary,
    WorkspaceMemberSummary,
    WorkspaceSummary,
)
from app.services.auth_service import create_workspace_for_user, list_user_workspaces, workspace_summary
from app.services.entitlement_service import assert_resource_quota
from app.services.workspace_management import (
    WorkspaceManagementError,
    accept_workspace_invitation,
    change_workspace_member_role,
    create_workspace_invitation,
    invitation_summary,
    list_workspace_invitations,
    list_workspace_members,
    member_summary,
    remove_workspace_member,
    revoke_workspace_invitation,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _service_error(exc: WorkspaceManagementError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


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


@router.get("/members", response_model=list[WorkspaceMemberSummary])
async def list_members(
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[WorkspaceMemberSummary]:
    return await list_workspace_members(db, context.workspace.id)


@router.get("/invitations", response_model=list[WorkspaceInvitationSummary])
async def list_invitations(
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[WorkspaceInvitationSummary]:
    require_workspace_role(context, "owner", "admin")
    return await list_workspace_invitations(db, context.workspace.id)


@router.post(
    "/invitations",
    response_model=WorkspaceInvitationCreated,
    status_code=status.HTTP_201_CREATED,
)
async def invite_member(
    data: WorkspaceInvitationCreateRequest,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceInvitationCreated:
    require_workspace_role(context, "owner", "admin")
    if context.membership.role == "admin" and data.role != "member":
        raise HTTPException(status_code=403, detail="Admins can invite members only")

    active_members = int(
        await db.scalar(
            select(func.count(Membership.id)).where(
                Membership.workspace_id == context.workspace.id,
                Membership.status == "active",
            )
        )
        or 0
    )
    pending_other_invitations = int(
        await db.scalar(
            select(func.count(WorkspaceInvitation.id)).where(
                WorkspaceInvitation.workspace_id == context.workspace.id,
                WorkspaceInvitation.status == "pending",
                WorkspaceInvitation.email != data.email,
            )
        )
        or 0
    )
    active_collaborators = max(active_members - 1, 0)
    await assert_resource_quota(
        db,
        workspace_id=context.workspace.id,
        metric="team_members",
        current=active_collaborators + pending_other_invitations,
    )

    try:
        invitation, raw_token = await create_workspace_invitation(
            db,
            workspace_id=context.workspace.id,
            invited_by_user_id=context.user.id,
            email=data.email,
            role=data.role,
        )
    except WorkspaceManagementError as exc:
        raise _service_error(exc) from exc

    summary = invitation_summary(invitation)
    return WorkspaceInvitationCreated(**summary.model_dump(), accept_token=raw_token)


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    invitation_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> Response:
    require_workspace_role(context, "owner", "admin")
    try:
        await revoke_workspace_invitation(
            db,
            workspace_id=context.workspace.id,
            invitation_id=invitation_id,
        )
    except WorkspaceManagementError as exc:
        raise _service_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/invitations/accept", response_model=WorkspaceSummary)
async def accept_invitation(
    data: WorkspaceInvitationAcceptRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceSummary:
    try:
        workspace, membership = await accept_workspace_invitation(
            db,
            current_user=current_user,
            token=data.token,
        )
    except WorkspaceManagementError as exc:
        raise _service_error(exc) from exc
    return workspace_summary(workspace, membership)


@router.patch("/members/{membership_id}", response_model=WorkspaceMemberSummary)
async def change_member_role(
    membership_id: uuid.UUID,
    data: MembershipRoleUpdateRequest,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceMemberSummary:
    require_workspace_role(context, "owner")
    try:
        membership, user = await change_workspace_member_role(
            db,
            workspace_id=context.workspace.id,
            membership_id=membership_id,
            role=data.role,
        )
    except WorkspaceManagementError as exc:
        raise _service_error(exc) from exc
    return member_summary(membership, user)


@router.delete("/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    membership_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> Response:
    require_workspace_role(context, "owner", "admin")

    target = await db.scalar(
        select(Membership).where(
            Membership.id == membership_id,
            Membership.workspace_id == context.workspace.id,
            Membership.status == "active",
        )
    )
    if not target:
        raise HTTPException(status_code=404, detail="Workspace member not found")
    if context.membership.role == "admin" and target.role != "member":
        raise HTTPException(status_code=403, detail="Admins can remove members only")

    try:
        await remove_workspace_member(
            db,
            workspace_id=context.workspace.id,
            membership_id=membership_id,
        )
    except WorkspaceManagementError as exc:
        raise _service_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
