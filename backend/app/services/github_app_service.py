from __future__ import annotations

import base64
import binascii
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

import httpx
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.github_app import (
    GitHubAppInstallation,
    GitHubAppInstallIntent,
    GitHubRepositoryConnection,
)
from app.models.site import Site


settings = get_settings()


class GitHubAppError(ValueError):
    def __init__(
        self,
        message: str,
        status_code: int = 400,
        *,
        code: str = "github_app_error",
        retryable: bool = False,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.retryable = retryable


def github_app_configured() -> bool:
    return bool(
        settings.github_app_id
        and settings.github_app_slug
        and settings.github_app_private_key_base64
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _state_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _private_key() -> str:
    if not github_app_configured():
        raise GitHubAppError(
            "The GitHub App is not configured for this environment",
            503,
            code="github_app_not_configured",
        )
    try:
        return base64.b64decode(
            settings.github_app_private_key_base64,
            validate=True,
        ).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise GitHubAppError(
            "The GitHub App private key configuration is invalid",
            503,
            code="github_app_key_invalid",
        ) from exc


def build_github_app_jwt(*, now: datetime | None = None) -> str:
    issued_at = now or _now()
    claims = {
        "iat": int((issued_at - timedelta(seconds=60)).timestamp()),
        "exp": int((issued_at + timedelta(minutes=9)).timestamp()),
        "iss": settings.github_app_id,
    }
    try:
        return jwt.encode(claims, _private_key(), algorithm="RS256")
    except Exception as exc:
        raise GitHubAppError(
            "The GitHub App private key could not sign an application token",
            503,
            code="github_app_key_invalid",
        ) from exc


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "SERP-Strategists-Operator",
    }


def _provider_error(response: httpx.Response, operation: str) -> GitHubAppError:
    retryable = response.status_code == 429 or response.status_code >= 500
    if response.status_code == 404:
        return GitHubAppError(
            f"GitHub could not find the {operation}",
            404,
            code="github_installation_not_found",
        )
    if response.status_code in {401, 403}:
        return GitHubAppError(
            f"GitHub rejected the {operation}; verify the GitHub App configuration and permissions",
            503,
            code="github_app_authorization_failed",
            retryable=False,
        )
    return GitHubAppError(
        f"GitHub could not complete the {operation}",
        502,
        code="github_provider_unavailable",
        retryable=retryable,
    )


def _provider_payload(response: httpx.Response, operation: str) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise GitHubAppError(
            f"GitHub returned an invalid {operation} response",
            502,
            code="github_provider_invalid_response",
            retryable=True,
        ) from exc
    if not isinstance(payload, dict):
        raise GitHubAppError(
            f"GitHub returned an invalid {operation} response",
            502,
            code="github_provider_invalid_response",
            retryable=True,
        )
    return payload


def _provider_request_error(operation: str, exc: httpx.RequestError) -> GitHubAppError:
    return GitHubAppError(
        f"GitHub could not complete the {operation}",
        502,
        code="github_provider_unavailable",
        retryable=True,
    )


async def fetch_provider_installation(
    installation_id: int,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict:
    owns_client = client is None
    provider = client or httpx.AsyncClient(
        timeout=settings.github_app_timeout_seconds,
        follow_redirects=False,
    )
    try:
        try:
            response = await provider.get(
                f"{settings.github_api_url}/app/installations/{installation_id}",
                headers=_headers(build_github_app_jwt()),
            )
        except httpx.RequestError as exc:
            raise _provider_request_error("GitHub App installation lookup", exc) from exc
        if response.status_code >= 400:
            raise _provider_error(response, "GitHub App installation")
        payload = _provider_payload(response, "installation")
        if not isinstance(payload.get("account"), dict):
            raise GitHubAppError(
                "GitHub returned an invalid installation response",
                502,
                code="github_provider_invalid_response",
                retryable=True,
            )
        return payload
    finally:
        if owns_client:
            await provider.aclose()


async def create_installation_token(
    installation_id: int,
    *,
    client: httpx.AsyncClient | None = None,
) -> str:
    owns_client = client is None
    provider = client or httpx.AsyncClient(
        timeout=settings.github_app_timeout_seconds,
        follow_redirects=False,
    )
    try:
        try:
            response = await provider.post(
                f"{settings.github_api_url}/app/installations/{installation_id}/access_tokens",
                headers=_headers(build_github_app_jwt()),
            )
        except httpx.RequestError as exc:
            raise _provider_request_error("installation access token request", exc) from exc
        if response.status_code >= 400:
            raise _provider_error(response, "installation access token")
        token = _provider_payload(response, "installation token").get("token")
        if not isinstance(token, str) or not token:
            raise GitHubAppError(
                "GitHub returned an invalid installation token response",
                502,
                code="github_provider_invalid_response",
                retryable=True,
            )
        return token
    finally:
        if owns_client:
            await provider.aclose()


async def list_provider_repositories(
    installation_id: int,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[dict]:
    owns_client = client is None
    provider = client or httpx.AsyncClient(
        timeout=settings.github_app_timeout_seconds,
        follow_redirects=False,
    )
    try:
        token = await create_installation_token(installation_id, client=provider)
        repositories: list[dict] = []
        for page in range(1, 6):
            try:
                response = await provider.get(
                    f"{settings.github_api_url}/installation/repositories",
                    headers=_headers(token),
                    params={"per_page": 100, "page": page},
                )
            except httpx.RequestError as exc:
                raise _provider_request_error("authorized repository list", exc) from exc
            if response.status_code >= 400:
                raise _provider_error(response, "authorized repository list")
            batch = _provider_payload(response, "repository list").get("repositories")
            if not isinstance(batch, list):
                raise GitHubAppError(
                    "GitHub returned an invalid repository response",
                    502,
                    code="github_provider_invalid_response",
                    retryable=True,
                )
            repositories.extend(item for item in batch if isinstance(item, dict))
            if len(batch) < 100:
                break
        return repositories
    finally:
        if owns_client:
            await provider.aclose()


async def create_install_intent(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
) -> str:
    if not github_app_configured():
        raise GitHubAppError(
            "The GitHub App is not configured for this environment",
            503,
            code="github_app_not_configured",
        )
    state = secrets.token_urlsafe(32)
    db.add(
        GitHubAppInstallIntent(
            workspace_id=workspace_id,
            user_id=user_id,
            state_hash=_state_hash(state),
            expires_at=_now() + timedelta(minutes=settings.github_app_state_ttl_minutes),
        )
    )
    await db.commit()
    query = urlencode({"state": state}, quote_via=quote)
    return f"https://github.com/apps/{settings.github_app_slug}/installations/new?{query}"


async def complete_installation(
    db: AsyncSession,
    *,
    state: str,
    installation_id: int,
) -> GitHubAppInstallation:
    intent = await db.scalar(
        select(GitHubAppInstallIntent)
        .where(GitHubAppInstallIntent.state_hash == _state_hash(state))
        .with_for_update()
    )
    if not intent or intent.consumed_at is not None or intent.expires_at <= _now():
        raise GitHubAppError(
            "The GitHub App installation session is invalid or expired",
            400,
            code="github_install_state_invalid",
        )
    payload = await fetch_provider_installation(installation_id)
    account = payload["account"]
    account_id = account.get("id")
    account_login = account.get("login")
    if not isinstance(account_id, int) or not isinstance(account_login, str) or not account_login:
        raise GitHubAppError(
            "GitHub returned an invalid installation response",
            502,
            code="github_provider_invalid_response",
            retryable=True,
        )
    existing = await db.scalar(
        select(GitHubAppInstallation)
        .where(GitHubAppInstallation.installation_id == installation_id)
        .with_for_update()
    )
    if existing and existing.workspace_id != intent.workspace_id:
        raise GitHubAppError(
            "This GitHub App installation is already connected to another workspace",
            409,
            code="github_installation_in_use",
        )
    installation = existing or GitHubAppInstallation(
        workspace_id=intent.workspace_id,
        installation_id=installation_id,
        account_id=account_id,
        account_login=account_login[:255],
        account_type=str(account.get("type") or "Unknown")[:64],
    )
    installation.workspace_id = intent.workspace_id
    installation.account_id = account_id
    installation.account_login = account_login[:255]
    installation.account_type = str(account.get("type") or "Unknown")[:64]
    installation.target_type = str(payload.get("target_type"))[:64] if payload.get("target_type") else None
    installation.repository_selection = str(payload.get("repository_selection") or "selected")[:32]
    installation.permissions = payload.get("permissions") if isinstance(payload.get("permissions"), dict) else {}
    installation.status = "suspended" if payload.get("suspended_at") else "active"
    installation.installed_by_user_id = intent.user_id
    installation.last_verified_at = _now()
    installation.revoked_at = None
    db.add(installation)
    intent.consumed_at = _now()
    await db.commit()
    await db.refresh(installation)
    return installation


async def workspace_installations(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
) -> list[GitHubAppInstallation]:
    return list(
        (
            await db.execute(
                select(GitHubAppInstallation)
                .where(GitHubAppInstallation.workspace_id == workspace_id)
                .order_by(GitHubAppInstallation.account_login, GitHubAppInstallation.id)
            )
        ).scalars().all()
    )


async def workspace_repositories(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
) -> list[tuple[GitHubAppInstallation, dict]]:
    installations = list(
        (
            await db.execute(
                select(GitHubAppInstallation).where(
                    GitHubAppInstallation.workspace_id == workspace_id,
                    GitHubAppInstallation.status == "active",
                )
            )
        ).scalars().all()
    )
    repositories: list[tuple[GitHubAppInstallation, dict]] = []
    for installation in installations:
        for repository in await list_provider_repositories(installation.installation_id):
            repositories.append((installation, repository))
        installation.last_verified_at = _now()
    if installations:
        await db.commit()
    return sorted(
        repositories,
        key=lambda value: str(value[1].get("full_name") or "").lower(),
    )


async def connect_authorized_repository(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    site_id: uuid.UUID,
    installation_record_id: uuid.UUID,
    repository_id: int,
) -> GitHubRepositoryConnection:
    site = await db.scalar(
        select(Site).where(Site.id == site_id, Site.workspace_id == workspace_id)
    )
    if not site:
        raise GitHubAppError("Site not found in this workspace", 404, code="site_not_found")
    installation = await db.scalar(
        select(GitHubAppInstallation).where(
            GitHubAppInstallation.id == installation_record_id,
            GitHubAppInstallation.workspace_id == workspace_id,
            GitHubAppInstallation.status == "active",
        )
    )
    if not installation:
        raise GitHubAppError(
            "Active GitHub App installation not found in this workspace",
            404,
            code="github_installation_not_found",
        )
    repository = next(
        (
            item
            for item in await list_provider_repositories(installation.installation_id)
            if int(item.get("id") or 0) == repository_id
        ),
        None,
    )
    if repository is None:
        raise GitHubAppError(
            "The selected repository is not authorized for this GitHub App installation",
            403,
            code="github_repository_not_authorized",
        )
    full_name = repository.get("full_name")
    if not isinstance(full_name, str) or "/" not in full_name:
        raise GitHubAppError(
            "GitHub returned an invalid repository response",
            502,
            code="github_provider_invalid_response",
            retryable=True,
        )
    connection = await db.scalar(
        select(GitHubRepositoryConnection).where(
            GitHubRepositoryConnection.site_id == site_id
        )
    )
    if connection is None:
        connection = GitHubRepositoryConnection(
            workspace_id=workspace_id,
            site_id=site_id,
            repository_full_name=full_name,
        )
        db.add(connection)
    connection.workspace_id = workspace_id
    connection.installation_id = installation.id
    connection.github_repository_id = repository_id
    connection.repository_full_name = full_name[:255]
    connection.visibility = str(repository.get("visibility") or ("private" if repository.get("private") else "public"))[:32]
    connection.default_branch = (
        str(repository.get("default_branch"))[:255] if repository.get("default_branch") else None
    )
    connection.permissions = repository.get("permissions") if isinstance(repository.get("permissions"), dict) else {}
    connection.status = "active"
    connection.last_verified_at = _now()
    site.github_repo = connection.repository_full_name
    site.cms = "github"
    await db.commit()
    await db.refresh(connection)
    return connection


async def disconnect_installation(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    installation_record_id: uuid.UUID,
) -> None:
    installation = await db.scalar(
        select(GitHubAppInstallation)
        .where(
            GitHubAppInstallation.id == installation_record_id,
            GitHubAppInstallation.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    if not installation:
        raise GitHubAppError(
            "GitHub App installation not found in this workspace",
            404,
            code="github_installation_not_found",
        )
    connections = list(
        (
            await db.execute(
                select(GitHubRepositoryConnection).where(
                    GitHubRepositoryConnection.installation_id == installation.id
                )
            )
        ).scalars().all()
    )
    site_ids = [connection.site_id for connection in connections]
    sites = list(
        (
            await db.execute(
                select(Site).where(Site.id.in_(site_ids), Site.workspace_id == workspace_id)
            )
        ).scalars().all()
    ) if site_ids else []
    for connection in connections:
        connection.status = "revoked"
    for site in sites:
        site.github_repo = None
        if site.cms == "github":
            site.cms = None
    installation.status = "revoked"
    installation.revoked_at = _now()
    await db.commit()
