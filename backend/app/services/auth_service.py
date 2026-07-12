from datetime import datetime, timedelta, timezone
import re
import uuid

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.billing import Subscription
from app.models.identity import Membership, User, Workspace
from app.schemas.auth import RegisterRequest, WorkspaceSummary
from app.services.entitlement_service import get_plan_entitlements

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


class AuthenticationError(ValueError):
    pass


class RegistrationError(ValueError):
    pass


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    return pwd_context.verify(password, password_hash)


def create_access_token(user: User) -> tuple[str, int]:
    settings = get_settings()
    expires_minutes = settings.access_token_expire_minutes
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": now + timedelta(minutes=expires_minutes),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    return token, expires_minutes * 60


def decode_access_token(token: str) -> uuid.UUID:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError as exc:
        raise AuthenticationError("Invalid or expired access token") from exc

    if payload.get("type") != "access" or not payload.get("sub"):
        raise AuthenticationError("Invalid access token")

    try:
        return uuid.UUID(str(payload["sub"]))
    except ValueError as exc:
        raise AuthenticationError("Invalid access token subject") from exc


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:100] or "workspace"


async def unique_workspace_slug(db: AsyncSession, name: str) -> str:
    base = slugify(name)
    candidate = base
    suffix = 2
    while await db.scalar(select(Workspace.id).where(Workspace.slug == candidate)):
        candidate = f"{base[:95]}-{suffix}"
        suffix += 1
    return candidate


async def create_workspace_for_user(
    db: AsyncSession,
    user: User,
    name: str,
    *,
    commit: bool = True,
) -> tuple[Workspace, Membership]:
    workspace = Workspace(
        name=name,
        slug=await unique_workspace_slug(db, name),
        created_by_user_id=user.id,
    )
    db.add(workspace)
    await db.flush()

    membership = Membership(
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        status="active",
    )
    subscription = Subscription(
        workspace_id=workspace.id,
        plan="audit",
        status="active",
        entitlements=get_plan_entitlements("audit"),
    )
    db.add_all([membership, subscription])

    if commit:
        await db.commit()
        await db.refresh(workspace)
        await db.refresh(membership)
    else:
        await db.flush()

    return workspace, membership


async def register_user(db: AsyncSession, data: RegisterRequest) -> tuple[User, Workspace, Membership]:
    existing = await db.scalar(select(User.id).where(User.email == data.email))
    if existing:
        raise RegistrationError("An account with this email already exists")

    user = User(
        email=data.email,
        name=data.name,
        password_hash=hash_password(data.password),
        status="active",
    )
    db.add(user)
    await db.flush()

    default_label = data.name or data.email.split("@", 1)[0]
    workspace_name = data.workspace_name or f"{default_label}'s Workspace"
    workspace, membership = await create_workspace_for_user(
        db,
        user,
        workspace_name,
        commit=False,
    )

    await db.commit()
    await db.refresh(user)
    await db.refresh(workspace)
    await db.refresh(membership)
    return user, workspace, membership


async def authenticate_user(db: AsyncSession, email: str, password: str) -> tuple[User, Membership, Workspace]:
    user = await db.scalar(select(User).where(User.email == email))
    if not user or user.status != "active" or not verify_password(password, user.password_hash):
        raise AuthenticationError("Invalid email or password")

    result = await db.execute(
        select(Membership, Workspace)
        .join(Workspace, Workspace.id == Membership.workspace_id)
        .where(
            Membership.user_id == user.id,
            Membership.status == "active",
            Workspace.status == "active",
        )
        .order_by(Membership.joined_at.asc())
        .limit(1)
    )
    row = result.first()
    if not row:
        raise AuthenticationError("No active workspace is available for this account")
    membership, workspace = row
    return user, membership, workspace


async def list_user_workspaces(db: AsyncSession, user_id: uuid.UUID) -> list[WorkspaceSummary]:
    result = await db.execute(
        select(Membership, Workspace)
        .join(Workspace, Workspace.id == Membership.workspace_id)
        .where(Membership.user_id == user_id, Membership.status == "active")
        .order_by(Workspace.created_at.asc())
    )
    return [
        WorkspaceSummary(
            id=workspace.id,
            name=workspace.name,
            slug=workspace.slug,
            role=membership.role,
            status=workspace.status,
        )
        for membership, workspace in result.all()
    ]


def workspace_summary(workspace: Workspace, membership: Membership) -> WorkspaceSummary:
    return WorkspaceSummary(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        role=membership.role,
        status=workspace.status,
    )
