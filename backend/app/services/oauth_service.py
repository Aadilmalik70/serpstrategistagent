from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import secrets
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.identity import Membership, OAuthIdentity, OAuthLinkIntent, User, Workspace
from app.schemas.auth import OAuthExchangeRequest, OAuthProviderSummary
from app.services.auth_service import create_workspace_for_user, verify_password


class OAuthServiceError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class OAuthAuthenticated:
    user: User
    membership: Membership
    workspace: Workspace


@dataclass(frozen=True)
class OAuthLinkRequired:
    token: str
    email: str
    expires_in: int


def oauth_signature_message(timestamp: str, data: OAuthExchangeRequest) -> str:
    return json.dumps(
        [
            timestamp,
            data.provider,
            data.provider_account_id,
            data.email,
            data.email_verified,
        ],
        separators=(",", ":"),
        ensure_ascii=False,
    )


def verify_oauth_bridge_signature(
    data: OAuthExchangeRequest,
    *,
    timestamp: str,
    signature: str,
    max_age_seconds: int = 120,
) -> None:
    settings = get_settings()
    secret = settings.oauth_bridge_secret
    if len(secret) < 32:
        raise OAuthServiceError("OAuth sign-in is not configured", 503)

    try:
        issued_at = int(timestamp)
    except (TypeError, ValueError) as exc:
        raise OAuthServiceError("Invalid OAuth bridge timestamp", 401) from exc

    if abs(int(time.time()) - issued_at) > max_age_seconds:
        raise OAuthServiceError("OAuth bridge assertion has expired", 401)

    expected = hmac.new(
        secret.encode("utf-8"),
        oauth_signature_message(timestamp, data).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature.strip().lower()):
        raise OAuthServiceError("Invalid OAuth bridge signature", 401)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _first_workspace(
    db: AsyncSession,
    user_id,
) -> tuple[Membership, Workspace]:
    row = (
        await db.execute(
            select(Membership, Workspace)
            .join(Workspace, Workspace.id == Membership.workspace_id)
            .where(
                Membership.user_id == user_id,
                Membership.status == "active",
                Workspace.status == "active",
            )
            .order_by(Membership.joined_at.asc())
            .limit(1)
        )
    ).first()
    if not row:
        raise OAuthServiceError("No active workspace is available for this account", 403)
    return row


def _apply_profile(user: User, data: OAuthExchangeRequest) -> None:
    if data.name and not user.name:
        user.name = data.name
    if data.image_url:
        user.image_url = data.image_url


async def _create_identity(
    db: AsyncSession,
    *,
    user: User,
    data: OAuthExchangeRequest,
    now: datetime,
) -> OAuthIdentity:
    claimed = await db.scalar(
        select(OAuthIdentity).where(
            OAuthIdentity.provider == data.provider,
            OAuthIdentity.provider_account_id == data.provider_account_id,
        )
    )
    if claimed and claimed.user_id != user.id:
        raise OAuthServiceError("This provider account is already linked", 409)

    same_provider = await db.scalar(
        select(OAuthIdentity).where(
            OAuthIdentity.user_id == user.id,
            OAuthIdentity.provider == data.provider,
        )
    )
    if same_provider:
        if same_provider.provider_account_id != data.provider_account_id:
            raise OAuthServiceError(
                f"A different {data.provider} account is already linked to this user",
                409,
            )
        same_provider.last_login_at = now
        same_provider.provider_email = data.email
        same_provider.email_verified = data.email_verified
        return same_provider

    identity = OAuthIdentity(
        user_id=user.id,
        provider=data.provider,
        provider_account_id=data.provider_account_id,
        provider_email=data.email,
        email_verified=data.email_verified,
        last_login_at=now,
    )
    db.add(identity)
    return identity


async def exchange_oauth_identity(
    db: AsyncSession,
    data: OAuthExchangeRequest,
) -> OAuthAuthenticated | OAuthLinkRequired:
    if not data.email_verified:
        raise OAuthServiceError("A verified provider email is required", 403)

    now = datetime.now(timezone.utc)
    row = (
        await db.execute(
            select(OAuthIdentity, User)
            .join(User, User.id == OAuthIdentity.user_id)
            .where(
                OAuthIdentity.provider == data.provider,
                OAuthIdentity.provider_account_id == data.provider_account_id,
            )
        )
    ).first()
    if row:
        identity, user = row
        if user.status != "active":
            raise OAuthServiceError("Account is unavailable", 403)
        identity.last_login_at = now
        identity.provider_email = data.email
        identity.email_verified = True
        _apply_profile(user, data)
        await db.commit()
        membership, workspace = await _first_workspace(db, user.id)
        return OAuthAuthenticated(user=user, membership=membership, workspace=workspace)

    user = await db.scalar(select(User).where(User.email == data.email))
    if not user:
        user = User(
            email=data.email,
            name=data.name,
            image_url=data.image_url,
            email_verified_at=now,
            status="active",
        )
        db.add(user)
        await db.flush()
        workspace_label = data.name or data.email.split("@", 1)[0]
        workspace, membership = await create_workspace_for_user(
            db,
            user,
            f"{workspace_label}'s Workspace",
            commit=False,
        )
        await _create_identity(db, user=user, data=data, now=now)
        await db.commit()
        await db.refresh(user)
        await db.refresh(workspace)
        await db.refresh(membership)
        return OAuthAuthenticated(user=user, membership=membership, workspace=workspace)

    if user.status != "active":
        raise OAuthServiceError("Account is unavailable", 403)

    if user.email_verified_at is not None:
        await _create_identity(db, user=user, data=data, now=now)
        _apply_profile(user, data)
        await db.commit()
        membership, workspace = await _first_workspace(db, user.id)
        return OAuthAuthenticated(user=user, membership=membership, workspace=workspace)

    if not user.password_hash:
        raise OAuthServiceError("This account cannot be linked automatically", 409)

    previous_intents = list(
        (
            await db.execute(
                select(OAuthLinkIntent).where(
                    OAuthLinkIntent.user_id == user.id,
                    OAuthLinkIntent.provider == data.provider,
                    OAuthLinkIntent.consumed_at.is_(None),
                )
            )
        ).scalars().all()
    )
    for intent in previous_intents:
        intent.consumed_at = now

    raw_token = secrets.token_urlsafe(32)
    expires_in = 10 * 60
    db.add(
        OAuthLinkIntent(
            user_id=user.id,
            provider=data.provider,
            provider_account_id=data.provider_account_id,
            provider_email=data.email,
            provider_name=data.name,
            provider_image_url=data.image_url,
            token_hash=_token_hash(raw_token),
            expires_at=now + timedelta(seconds=expires_in),
        )
    )
    await db.commit()
    return OAuthLinkRequired(token=raw_token, email=user.email, expires_in=expires_in)


async def confirm_oauth_link(
    db: AsyncSession,
    *,
    token: str,
    password: str,
) -> OAuthAuthenticated:
    now = datetime.now(timezone.utc)
    row = (
        await db.execute(
            select(OAuthLinkIntent, User)
            .join(User, User.id == OAuthLinkIntent.user_id)
            .where(
                OAuthLinkIntent.token_hash == _token_hash(token),
                OAuthLinkIntent.consumed_at.is_(None),
            )
        )
    ).first()
    if not row:
        raise OAuthServiceError("Link request is invalid or already used", 404)

    intent, user = row
    if _aware(intent.expires_at) <= now:
        intent.consumed_at = now
        await db.commit()
        raise OAuthServiceError("Link request has expired", 410)
    if user.status != "active" or not verify_password(password, user.password_hash):
        raise OAuthServiceError("Password confirmation failed", 401)

    data = OAuthExchangeRequest(
        provider=intent.provider,
        provider_account_id=intent.provider_account_id,
        email=intent.provider_email,
        email_verified=True,
        name=intent.provider_name,
        image_url=intent.provider_image_url,
    )
    await _create_identity(db, user=user, data=data, now=now)
    user.email_verified_at = user.email_verified_at or now
    _apply_profile(user, data)
    intent.consumed_at = now
    await db.commit()
    membership, workspace = await _first_workspace(db, user.id)
    return OAuthAuthenticated(user=user, membership=membership, workspace=workspace)


async def list_oauth_providers(db: AsyncSession, user_id) -> list[OAuthProviderSummary]:
    identities = list(
        (
            await db.execute(
                select(OAuthIdentity)
                .where(OAuthIdentity.user_id == user_id)
                .order_by(OAuthIdentity.created_at.asc())
            )
        ).scalars().all()
    )
    return [
        OAuthProviderSummary(
            provider=identity.provider,
            email=identity.provider_email,
            linked_at=identity.created_at,
            last_login_at=identity.last_login_at,
        )
        for identity in identities
    ]
