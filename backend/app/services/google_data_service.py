from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import urllib.parse
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.google_data_connection import GoogleDataConnection
from app.schemas.google_data import GoogleDataConnectionResponse, GooglePropertyOption
from app.services.credential_vault import CredentialVaultError, get_credential_vault


SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",
]


class GoogleDataServiceError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _oauth_config() -> tuple[str, str, str, str]:
    settings = get_settings()
    client_id = settings.google_integration_client_id.strip()
    client_secret = settings.google_integration_client_secret.strip()
    redirect_uri = settings.google_integration_redirect_uri.strip()
    frontend_url = settings.frontend_url.rstrip("/")
    if not client_id or not client_secret or not redirect_uri:
        raise GoogleDataServiceError("Google data integration is not configured", 503)
    return client_id, client_secret, redirect_uri, frontend_url


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def connection_response(connection: GoogleDataConnection | None) -> GoogleDataConnectionResponse:
    if connection is None:
        return GoogleDataConnectionResponse(
            status="not_connected",
            google_email=None,
            scopes=[],
            gsc_property=None,
            ga4_property_id=None,
            ga4_property_name=None,
            baseline_status="not_started",
            baseline_summary={},
            last_synced_at=None,
            connected_at=None,
            last_refreshed_at=None,
            last_error=None,
        )
    return GoogleDataConnectionResponse(
        status=connection.status,
        google_email=connection.google_email,
        scopes=connection.scopes or [],
        gsc_property=connection.gsc_property,
        ga4_property_id=connection.ga4_property_id,
        ga4_property_name=connection.ga4_property_name,
        baseline_status=connection.baseline_status,
        baseline_summary=connection.baseline_summary or {},
        last_synced_at=connection.last_synced_at,
        connected_at=connection.connected_at,
        last_refreshed_at=connection.last_refreshed_at,
        last_error=connection.last_error,
    )


async def get_connection(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
) -> GoogleDataConnection | None:
    return await db.scalar(
        select(GoogleDataConnection).where(
            GoogleDataConnection.workspace_id == workspace_id,
            GoogleDataConnection.user_id == user_id,
        )
    )


async def start_google_oauth(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
) -> str:
    settings = get_settings()
    client_id, _, redirect_uri, _ = _oauth_config()
    connection = await get_connection(db, workspace_id, user_id)
    if connection is None:
        connection = GoogleDataConnection(workspace_id=workspace_id, user_id=user_id)
        db.add(connection)
        await db.flush()

    state = secrets.token_urlsafe(32)
    connection.oauth_state_hash = _hash(state)
    connection.oauth_state_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    connection.last_error = None
    await db.commit()

    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
    )
    return f"{settings.google_oauth_authorize_url}?{query}"


async def complete_google_oauth(db: AsyncSession, code: str, state: str) -> str:
    settings = get_settings()
    client_id, client_secret, redirect_uri, frontend_url = _oauth_config()
    connection = await db.scalar(
        select(GoogleDataConnection).where(GoogleDataConnection.oauth_state_hash == _hash(state))
    )
    now = datetime.now(timezone.utc)
    if not connection or not connection.oauth_state_expires_at or connection.oauth_state_expires_at < now:
        raise GoogleDataServiceError("Google authorization state is invalid or expired", 400)

    async with httpx.AsyncClient(timeout=settings.google_integration_timeout_seconds) as client:
        token_response = await client.post(
            settings.google_oauth_token_url,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_response.status_code >= 400:
            connection.status = "error"
            connection.last_error = "Google token exchange failed"
            connection.oauth_state_hash = None
            connection.oauth_state_expires_at = None
            await db.commit()
            raise GoogleDataServiceError("Google token exchange failed", 400)
        tokens = token_response.json()
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        if not access_token:
            raise GoogleDataServiceError("Google did not return an access token", 400)

        userinfo = await client.get(
            settings.google_userinfo_url,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        email = userinfo.json().get("email") if userinfo.status_code < 400 else None

    existing_payload: dict = {}
    if connection.encrypted_tokens:
        try:
            existing_payload = get_credential_vault().decrypt(connection.encrypted_tokens)
        except CredentialVaultError:
            existing_payload = {}
    payload = {
        "access_token": access_token,
        "refresh_token": refresh_token or existing_payload.get("refresh_token"),
        "expires_at": int(now.timestamp()) + int(tokens.get("expires_in", 3600)),
        "token_type": tokens.get("token_type", "Bearer"),
    }
    if not payload["refresh_token"]:
        raise GoogleDataServiceError("Google did not return a refresh token; authorize again", 400)

    encrypted, fingerprint = get_credential_vault().encrypt(payload)
    connection.encrypted_tokens = encrypted
    connection.token_fingerprint = fingerprint
    connection.google_email = email
    connection.scopes = str(tokens.get("scope", " ".join(SCOPES))).split()
    connection.status = "connected"
    connection.baseline_status = "not_started"
    connection.baseline_summary = {}
    connection.last_synced_at = None
    connection.connected_at = connection.connected_at or now
    connection.last_refreshed_at = now
    connection.last_error = None
    connection.oauth_state_hash = None
    connection.oauth_state_expires_at = None
    await db.commit()
    return f"{frontend_url}/onboarding?step=google&connected=1"


async def _access_token(db: AsyncSession, connection: GoogleDataConnection) -> str:
    settings = get_settings()
    client_id, client_secret, _, _ = _oauth_config()
    if not connection.encrypted_tokens:
        raise GoogleDataServiceError("Google data connection is not available", 409)
    try:
        payload = get_credential_vault().decrypt(connection.encrypted_tokens)
    except CredentialVaultError as exc:
        raise GoogleDataServiceError("Google credentials could not be decrypted", 503) from exc

    expires_at = int(payload.get("expires_at", 0))
    if expires_at > int(datetime.now(timezone.utc).timestamp()) + 60:
        return str(payload["access_token"])
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        raise GoogleDataServiceError("Google refresh token is unavailable; reconnect the account", 409)

    async with httpx.AsyncClient(timeout=settings.google_integration_timeout_seconds) as client:
        response = await client.post(
            settings.google_oauth_token_url,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
    if response.status_code >= 400:
        connection.status = "expired"
        connection.last_error = "Google token refresh failed"
        await db.commit()
        raise GoogleDataServiceError("Google authorization expired; reconnect the account", 401)
    updated = response.json()
    payload["access_token"] = updated["access_token"]
    payload["expires_at"] = int(datetime.now(timezone.utc).timestamp()) + int(updated.get("expires_in", 3600))
    encrypted, fingerprint = get_credential_vault().encrypt(payload)
    connection.encrypted_tokens = encrypted
    connection.token_fingerprint = fingerprint
    connection.last_refreshed_at = datetime.now(timezone.utc)
    await db.commit()
    return str(updated["access_token"])


async def list_google_properties(
    db: AsyncSession,
    connection: GoogleDataConnection,
) -> tuple[list[GooglePropertyOption], list[GooglePropertyOption]]:
    settings = get_settings()
    token = await _access_token(db, connection)
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=settings.google_integration_timeout_seconds) as client:
        gsc_response = await client.get(
            f"{settings.google_search_console_api_url}/sites",
            headers=headers,
        )
        ga4_response = await client.get(
            f"{settings.google_analytics_admin_api_url}/accountSummaries",
            headers=headers,
            params={"pageSize": 200},
        )
    if gsc_response.status_code >= 400:
        raise GoogleDataServiceError("Search Console properties could not be loaded", 502)
    if ga4_response.status_code >= 400:
        raise GoogleDataServiceError("GA4 properties could not be loaded", 502)

    gsc = [
        GooglePropertyOption(
            id=item.get("siteUrl", ""),
            name=item.get("siteUrl", ""),
            type="gsc",
            permission_level=item.get("permissionLevel"),
        )
        for item in gsc_response.json().get("siteEntry", [])
        if item.get("siteUrl")
    ]
    ga4: list[GooglePropertyOption] = []
    for account in ga4_response.json().get("accountSummaries", []):
        for prop in account.get("propertySummaries", []):
            resource_name = prop.get("property", "")
            property_id = resource_name.split("/")[-1] if resource_name else ""
            if property_id:
                ga4.append(
                    GooglePropertyOption(
                        id=property_id,
                        name=prop.get("displayName") or property_id,
                        type="ga4",
                    )
                )
    return gsc, ga4
