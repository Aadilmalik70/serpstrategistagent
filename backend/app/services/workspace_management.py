from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Membership, User, Workspace, WorkspaceInvitation
from app.schemas.auth import WorkspaceInvitationSummary, WorkspaceMemberSummary


class WorkspaceManagementError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def invitation_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def member_summary(membership: Membership, user: User) -> WorkspaceMemberSummary:
    return WorkspaceMemberSummary(
        id=membership.id,
        user_id=user.id,
        email=user.email,
        name=user.name,
        role=membership.role,
        status=membership.status,
        joined_at=membership.joined_at,
    )


def invitation_summary(invitation: WorkspaceInvitation) -> WorkspaceInvitationSummary:
    return WorkspaceInvitationSummary(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        status=invitation.status,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
    )


async def list_workspace_members(
    db: AsyncSession,
    workspace_id: uuid.UUID,
) -> list[WorkspaceMemberSummary]:
    rows = (
        await db.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.workspace_id == workspace_id,
                Membership.status == "active",
            )
            .order_by(Membership.joined_at.asc())
        )
    ).all()
    return [member_summary(membership, user) for membership, user in rows]


async def list_workspace_invitations(
    db: AsyncSession,
    workspace_id: uuid.UUID,
) -> list[WorkspaceInvitationSummary]:
    invitations = list(
        (
            await db.execute(
                select(WorkspaceInvitation)
                .where(
                    WorkspaceInvitation.workspace_id == workspace_id,
                    WorkspaceInvitation.status == "pending",
                )
                .order_by(WorkspaceInvitation.created_at.desc())
            )
        ).scalars().all()
    )
    return [invitation_summary(invitation) for invitation in invitations]


async def create_workspace_invitation(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    invited_by_user_id: uuid.UUID,
    email: str,
    role: str,
) -> tuple[WorkspaceInvitation, str]:
    existing_member = await db.scalar(
        select(Membership.id)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.workspace_id == workspace_id,
            Membership.status == "active",
            User.email == email,
        )
    )
    if existing_member:
        raise WorkspaceManagementError("This person is already a workspace member", 409)

    pending = list(
        (
            await db.execute(
                select(WorkspaceInvitation).where(
                    WorkspaceInvitation.workspace_id == workspace_id,
                    WorkspaceInvitation.email == email,
                    WorkspaceInvitation.status == "pending",
                )
            )
        ).scalars().all()
    )
    for invitation in pending:
        invitation.status = "revoked"

    raw_token = secrets.token_urlsafe(32)
    invitation = WorkspaceInvitation(
        workspace_id=workspace_id,
        email=email,
        role=role,
        token_hash=invitation_token_hash(raw_token),
        status="pending",
        invited_by_user_id=invited_by_user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)
    return invitation, raw_token


async def accept_workspace_invitation(
    db: AsyncSession,
    *,
    current_user: User,
    token: str,
) -> tuple[Workspace, Membership]:
    token_hash = invitation_token_hash(token)
    row = (
        await db.execute(
            select(WorkspaceInvitation, Workspace)
            .join(Workspace, Workspace.id == WorkspaceInvitation.workspace_id)
            .where(
                WorkspaceInvitation.token_hash == token_hash,
                WorkspaceInvitation.status == "pending",
                Workspace.status == "active",
            )
        )
    ).first()
    if not row:
        raise WorkspaceManagementError("Invitation is invalid or no longer available", 404)

    invitation, workspace = row
    now = datetime.now(timezone.utc)
    expires_at = invitation.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        invitation.status = "expired"
        await db.commit()
        raise WorkspaceManagementError("Invitation has expired", 410)

    if invitation.email.lower() != current_user.email.lower():
        raise WorkspaceManagementError(
            "Sign in with the email address that received this invitation",
            403,
        )

    membership = await db.scalar(
        select(Membership).where(
            Membership.workspace_id == invitation.workspace_id,
            Membership.user_id == current_user.id,
        )
    )
    if membership:
        membership.role = invitation.role
        membership.status = "active"
    else:
        membership = Membership(
            workspace_id=invitation.workspace_id,
            user_id=current_user.id,
            role=invitation.role,
            status="active",
            invited_by_user_id=invitation.invited_by_user_id,
        )
        db.add(membership)

    invitation.status = "accepted"
    invitation.accepted_at = now
    await db.commit()
    await db.refresh(membership)
    return workspace, membership


async def revoke_workspace_invitation(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    invitation_id: uuid.UUID,
) -> WorkspaceInvitation:
    invitation = await db.scalar(
        select(WorkspaceInvitation).where(
            WorkspaceInvitation.id == invitation_id,
            WorkspaceInvitation.workspace_id == workspace_id,
            WorkspaceInvitation.status == "pending",
        )
    )
    if not invitation:
        raise WorkspaceManagementError("Invitation not found", 404)
    invitation.status = "revoked"
    await db.commit()
    return invitation


async def _active_owner_count(db: AsyncSession, workspace_id: uuid.UUID) -> int:
    return int(
        await db.scalar(
            select(func.count(Membership.id)).where(
                Membership.workspace_id == workspace_id,
                Membership.status == "active",
                Membership.role == "owner",
            )
        )
        or 0
    )


async def change_workspace_member_role(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    membership_id: uuid.UUID,
    role: str,
) -> tuple[Membership, User]:
    row = (
        await db.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.id == membership_id,
                Membership.workspace_id == workspace_id,
                Membership.status == "active",
            )
        )
    ).first()
    if not row:
        raise WorkspaceManagementError("Workspace member not found", 404)

    membership, user = row
    if membership.role == "owner" and role != "owner":
        if await _active_owner_count(db, workspace_id) <= 1:
            raise WorkspaceManagementError("The final workspace owner cannot be demoted", 409)

    membership.role = role
    await db.commit()
    await db.refresh(membership)
    return membership, user


async def remove_workspace_member(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    membership_id: uuid.UUID,
) -> Membership:
    membership = await db.scalar(
        select(Membership).where(
            Membership.id == membership_id,
            Membership.workspace_id == workspace_id,
            Membership.status == "active",
        )
    )
    if not membership:
        raise WorkspaceManagementError("Workspace member not found", 404)

    if membership.role == "owner" and await _active_owner_count(db, workspace_id) <= 1:
        raise WorkspaceManagementError("The final workspace owner cannot be removed", 409)

    membership.status = "removed"
    await db.commit()
    return membership
