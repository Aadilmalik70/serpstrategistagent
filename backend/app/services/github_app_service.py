from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import os
import secrets
from urllib.parse import urlencode
import uuid

import httpx
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.github_app import GitHubAppInstallation, GitHubAppInstallIntent
from app.models.site import Site
from app.schemas.github_app import GitHubAppRepository
from app.services.site_service import get_site_by_id


class GitHubAppServiceError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _state_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _private_key() -> str:
    encoded = os.getenv("GITHUB_APP_PRIVATE_KEY_BASE64", "").strip()
    raw = os.getenv("GITHUB_APP_PRIVATE_KEY", "").strip()
    if encoded:
        try:
            return base64.b64decode(encoded).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise GitHubAppServiceError("GitHub App private key configuration is invalid", 503) from exc
    if raw:
        return raw.replace("\\n", "\n")
    raise GitHubAppServiceError("GitHub App private key is not configured", 503)


def github_app_config() -> tuple[str, str]:
    app_id = os.getenv("GITHUB_APP_ID", "").strip()
    slug = os.getenv("GITHUB_APP_SLUG", "").strip()
    if not app_id or not slug:
        raise GitHubAppServiceError("GitHub App is not configured", 503)
    _private_key()
    return app_id, slug


def github_app_configured() -> bool:
    try:
        github_app_config()
        return True
    except GitHubAppServiceError:
        return False


def _app_jwt() -> str:
    app_id, _ = github_app_config()
    now = int(datetime.now(timezone.utc).timestamp())
    return jwt.encode(
        {"iat": now - 60, "exp": now + 540, "iss": app_id},
        _private_key(),
        algorithm="RS256",
    )


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "SERP-Strategists-GitHub-App",
    }


async def _installation_token(installation_id: int) -> str:
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        response = await client.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers=_github_headers(_app_jwt()),
        )
    if response.status_code in {401, 403, 404}:
        raise GitHubAppServiceError("GitHub App installation is unavailable or no longer authorized", 409)
    if response.status_code >= 400:
        raise GitHubAppServiceError("GitHub could not create an installation token", 502)
    token = response.json().get("token")
    if not token:
        raise GitHubAppServiceError("GitHub did not return an installation token", 502)
    return str(token)


async def _installation_details(installation_id: int) -> dict:
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        response = await client.get(
            f"https://api.github.com/app/installations/{installation_id}",
            headers=_github_headers(_app_jwt()),
        )
    if response.status_code == 404:
        raise GitHubAppServiceError("GitHub App installation was not found", 404)
    if response.status_code >= 400:
        raise GitHubAppServiceError("GitHub installation details could not be loaded", 502)
    payload = response.json()
    if not isinstance(payload, dict):
        raise GitHubAppServiceError("GitHub returned an invalid installation response", 502)
    return payload


async def start_installation(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    site_id: uuid.UUID,
) -> str:
    _, slug = github_app_config()
    site = await get_site_by_id(db, site_id, workspace_id)
    if not site:
        raise GitHubAppServiceError("Site not found", 404)

    state = secrets.token_urlsafe(32)
    intent = GitHubAppInstallIntent(
        workspace_id=workspace_id,
        user_id=user_id,
        site_id=site.id,
        state_hash=_state_hash(state),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    db.add(intent)
    await db.commit()
    query = urlencode({"state": state})
    return f"https://github.com/apps/{slug}/installations/new?{query}"


async def complete_installation(
    db: AsyncSession,
    *,
    installation_id: int,
    state: str,
) -> str:
    now = datetime.now(timezone.utc)
    intent = await db.scalar(
        select(GitHubAppInstallIntent).where(
            GitHubAppInstallIntent.state_hash == _state_hash(state),
            GitHubAppInstallIntent.consumed_at.is_(None),
        )
    )
    if not intent or intent.expires_at < now:
        raise GitHubAppServiceError("GitHub installation state is invalid or expired", 400)

    details = await _installation_details(installation_id)
    account = details.get("account") or {}
    account_login = account.get("login")
    if not account_login:
        raise GitHubAppServiceError("GitHub installation account is unavailable", 502)

    installation = await db.scalar(
        select(GitHubAppInstallation).where(
            GitHubAppInstallation.workspace_id == intent.workspace_id,
            GitHubAppInstallation.installation_id == installation_id,
        )
    )
    if installation is None:
        installation = GitHubAppInstallation(
            workspace_id=intent.workspace_id,
            installed_by_user_id=intent.user_id,
            installation_id=installation_id,
            account_login=str(account_login),
        )
        db.add(installation)
    installation.installed_by_user_id = intent.user_id
    installation.account_login = str(account_login)
    installation.account_type = account.get("type")
    installation.repository_selection = details.get("repository_selection")
    installation.permissions = details.get("permissions") or {}
    installation.status = "active"
    intent.consumed_at = now
    await db.commit()

    frontend = get_settings().frontend_url.rstrip("/")
    return f"{frontend}/onboarding?step=cms&github_installed=1"


async def list_installation_repositories(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
) -> list[GitHubAppRepository]:
    installations = list(
        (
            await db.execute(
                select(GitHubAppInstallation).where(
                    GitHubAppInstallation.workspace_id == workspace_id,
                    GitHubAppInstallation.status == "active",
                )
            )
        )
        .scalars()
        .all()
    )
    repositories: list[GitHubAppRepository] = []
    for installation in installations:
        token = await _installation_token(installation.installation_id)
        page = 1
        while page <= 10:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
                response = await client.get(
                    "https://api.github.com/installation/repositories",
                    headers=_github_headers(token),
                    params={"per_page": 100, "page": page},
                )
            if response.status_code >= 400:
                raise GitHubAppServiceError("GitHub repositories could not be loaded", 502)
            batch = response.json().get("repositories", [])
            for repository in batch:
                full_name = repository.get("full_name")
                if full_name:
                    repositories.append(
                        GitHubAppRepository(
                            installation_record_id=installation.id,
                            installation_id=installation.installation_id,
                            account_login=installation.account_login,
                            full_name=str(full_name),
                            private=bool(repository.get("private")),
                            default_branch=repository.get("default_branch"),
                        )
                    )
            if len(batch) < 100:
                break
            page += 1
    return sorted(repositories, key=lambda item: item.full_name.lower())


async def select_repository(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    site_id: uuid.UUID,
    installation_record_id: uuid.UUID,
    repository: str,
) -> Site:
    site = await get_site_by_id(db, site_id, workspace_id)
    if not site:
        raise GitHubAppServiceError("Site not found", 404)
    installation = await db.scalar(
        select(GitHubAppInstallation).where(
            GitHubAppInstallation.id == installation_record_id,
            GitHubAppInstallation.workspace_id == workspace_id,
            GitHubAppInstallation.status == "active",
        )
    )
    if not installation:
        raise GitHubAppServiceError("GitHub App installation not found", 404)

    repositories = await list_installation_repositories(db, workspace_id=workspace_id)
    allowed = {
        item.full_name
        for item in repositories
        if item.installation_record_id == installation.id
    }
    normalized = repository.strip().strip("/")
    if normalized not in allowed:
        raise GitHubAppServiceError("Repository is not accessible to this GitHub App installation", 403)

    site.github_app_installation_id = installation.id
    site.github_repo = normalized
    site.cms = "github"
    await db.commit()
    await db.refresh(site)
    return site
