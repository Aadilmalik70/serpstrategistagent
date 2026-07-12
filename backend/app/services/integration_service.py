from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration_credential import IntegrationCredential
from app.models.site import Site
from app.schemas.integration import (
    IntegrationCredentialResponse,
    IntegrationFieldDefinition,
    IntegrationProviderDefinition,
)
from app.services.credential_vault import CredentialVaultError, get_credential_vault


class IntegrationServiceError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ProviderField:
    name: str
    label: str
    secret: bool
    required: bool = True
    placeholder: str | None = None
    help_text: str | None = None


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    name: str
    description: str
    connection_mode: str
    scope: str
    available: bool
    test_supported: bool
    fields: tuple[ProviderField, ...]


PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "openai": ProviderSpec(
        id="openai",
        name="OpenAI",
        description="Use workspace-managed OpenAI models for planning and analysis.",
        connection_mode="api_key",
        scope="workspace",
        available=True,
        test_supported=True,
        fields=(
            ProviderField("api_key", "API key", True, placeholder="sk-…"),
            ProviderField("organization", "Organization ID", False, False, "org-…"),
            ProviderField("project", "Project ID", False, False, "proj_…"),
            ProviderField(
                "base_url",
                "API base URL",
                False,
                False,
                "https://api.openai.com",
                "Leave empty for the official OpenAI API.",
            ),
        ),
    ),
    "gemini": ProviderSpec(
        id="gemini",
        name="Gemini",
        description="Use the Gemini API for generative analysis and structured outputs.",
        connection_mode="api_key",
        scope="workspace",
        available=True,
        test_supported=True,
        fields=(ProviderField("api_key", "API key", True, placeholder="AIza…"),),
    ),
    "serpapi": ProviderSpec(
        id="serpapi",
        name="SerpApi",
        description="Fetch Google search results and account-level search usage.",
        connection_mode="api_key",
        scope="workspace",
        available=True,
        test_supported=True,
        fields=(ProviderField("api_key", "API key", True),),
    ),
    "serper": ProviderSpec(
        id="serper",
        name="Serper",
        description="Run lightweight Google SERP queries through Serper.",
        connection_mode="api_key",
        scope="workspace",
        available=True,
        test_supported=True,
        fields=(ProviderField("api_key", "API key", True),),
    ),
    "wordpress": ProviderSpec(
        id="wordpress",
        name="WordPress",
        description="Connect one site through a WordPress application password.",
        connection_mode="application_password",
        scope="site",
        available=True,
        test_supported=True,
        fields=(
            ProviderField("url", "WordPress URL", False, placeholder="https://example.com"),
            ProviderField("username", "Username", False),
            ProviderField("application_password", "Application password", True),
        ),
    ),
    "google_search_console": ProviderSpec(
        id="google_search_console",
        name="Google Search Console",
        description="OAuth connection foundation for property and Search Analytics sync.",
        connection_mode="oauth",
        scope="workspace",
        available=False,
        test_supported=False,
        fields=(),
    ),
    "google_analytics": ProviderSpec(
        id="google_analytics",
        name="Google Analytics 4",
        description="OAuth connection foundation for GA4 property and measurement sync.",
        connection_mode="oauth",
        scope="workspace",
        available=False,
        test_supported=False,
        fields=(),
    ),
}


def provider_catalog() -> list[IntegrationProviderDefinition]:
    return [
        IntegrationProviderDefinition(
            id=spec.id,
            name=spec.name,
            description=spec.description,
            connection_mode=spec.connection_mode,
            scope=spec.scope,
            available=spec.available,
            test_supported=spec.test_supported,
            fields=[
                IntegrationFieldDefinition(
                    name=field.name,
                    label=field.label,
                    secret=field.secret,
                    required=field.required,
                    placeholder=field.placeholder,
                    help_text=field.help_text,
                )
                for field in spec.fields
            ],
        )
        for spec in PROVIDER_SPECS.values()
    ]


def _provider(provider: str) -> ProviderSpec:
    spec = PROVIDER_SPECS.get(provider)
    if not spec or not spec.available:
        raise IntegrationServiceError("This integration is not available for manual connection", 400)
    return spec


def _scope_key(site_id: uuid.UUID | None) -> str:
    return str(site_id) if site_id else "workspace"


def _normalize_url(value: str, field_name: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise IntegrationServiceError(f"{field_name} must be an absolute HTTP or HTTPS URL")
    if parsed.username or parsed.password:
        raise IntegrationServiceError(f"{field_name} cannot contain embedded credentials")
    return normalized


def validate_credentials(provider: str, credentials: dict[str, Any]) -> dict[str, str]:
    spec = _provider(provider)
    if not isinstance(credentials, dict) or not credentials:
        raise IntegrationServiceError("Credential values are required")

    allowed = {field.name for field in spec.fields}
    unknown = sorted(set(credentials) - allowed)
    if unknown:
        raise IntegrationServiceError(f"Unsupported credential fields: {', '.join(unknown)}")

    normalized: dict[str, str] = {}
    for field in spec.fields:
        raw = credentials.get(field.name)
        if raw is None:
            if field.required:
                raise IntegrationServiceError(f"{field.label} is required")
            continue
        if not isinstance(raw, str):
            raise IntegrationServiceError(f"{field.label} must be text")
        value = raw.strip()
        if not value:
            if field.required:
                raise IntegrationServiceError(f"{field.label} is required")
            continue
        if len(value) > 4096:
            raise IntegrationServiceError(f"{field.label} is too long")
        normalized[field.name] = value

    if provider == "wordpress":
        normalized["url"] = _normalize_url(normalized["url"], "WordPress URL")
    if provider == "openai" and normalized.get("base_url"):
        normalized["base_url"] = _normalize_url(normalized["base_url"], "OpenAI base URL")
    return normalized


def safe_metadata(provider: str, credentials: dict[str, str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    secret_name = next(
        (field.name for field in _provider(provider).fields if field.secret and credentials.get(field.name)),
        None,
    )
    if secret_name:
        secret = credentials[secret_name]
        metadata["secret_hint"] = f"••••{secret[-4:]}" if len(secret) >= 4 else "••••"

    if provider == "openai":
        if credentials.get("organization"):
            metadata["organization"] = credentials["organization"]
        if credentials.get("project"):
            metadata["project"] = credentials["project"]
        if credentials.get("base_url"):
            metadata["base_url"] = credentials["base_url"]
    elif provider == "wordpress":
        metadata["url"] = credentials["url"]
        metadata["username"] = credentials["username"]
    return metadata


async def _require_site(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    site_id: uuid.UUID | None,
    spec: ProviderSpec,
) -> Site | None:
    if spec.scope == "site" and site_id is None:
        raise IntegrationServiceError("This integration must be connected to a site")
    if spec.scope == "workspace" and site_id is not None:
        raise IntegrationServiceError("This integration is workspace-scoped")
    if site_id is None:
        return None

    site = await db.scalar(
        select(Site).where(Site.id == site_id, Site.workspace_id == workspace_id)
    )
    if not site:
        raise IntegrationServiceError("Site not found in this workspace", 404)
    return site


def integration_response(credential: IntegrationCredential) -> IntegrationCredentialResponse:
    spec = PROVIDER_SPECS.get(credential.provider)
    return IntegrationCredentialResponse(
        id=credential.id,
        provider=credential.provider,
        provider_name=spec.name if spec else credential.provider.replace("_", " ").title(),
        label=credential.label,
        site_id=credential.site_id,
        scope="site" if credential.site_id else "workspace",
        external_account_id=credential.external_account_id,
        status=credential.status,
        metadata=credential.credential_metadata or {},
        last_validation_status=credential.last_validation_status,
        last_validation_error=credential.last_validation_error,
        last_validated_at=credential.last_validated_at,
        rotated_at=credential.rotated_at,
        revoked_at=credential.revoked_at,
        created_at=credential.created_at,
        updated_at=credential.updated_at,
        test_supported=bool(spec and spec.test_supported),
    )


async def list_integrations(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    site_id: uuid.UUID | None = None,
    include_revoked: bool = False,
) -> list[IntegrationCredentialResponse]:
    query = select(IntegrationCredential).where(
        IntegrationCredential.workspace_id == workspace_id
    )
    if site_id is not None:
        query = query.where(IntegrationCredential.site_id == site_id)
    if not include_revoked:
        query = query.where(IntegrationCredential.status != "revoked")
    query = query.order_by(IntegrationCredential.provider, IntegrationCredential.created_at)
    credentials = list((await db.execute(query)).scalars().all())
    return [integration_response(credential) for credential in credentials]


async def get_integration(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    credential_id: uuid.UUID,
) -> IntegrationCredential:
    credential = await db.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.id == credential_id,
            IntegrationCredential.workspace_id == workspace_id,
        )
    )
    if not credential:
        raise IntegrationServiceError("Integration not found", 404)
    return credential


async def create_integration(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    provider: str,
    label: str,
    site_id: uuid.UUID | None,
    external_account_id: str,
    credentials: dict[str, Any],
) -> IntegrationCredentialResponse:
    spec = _provider(provider)
    await _require_site(db, workspace_id=workspace_id, site_id=site_id, spec=spec)
    normalized = validate_credentials(provider, credentials)
    scope_key = _scope_key(site_id)

    existing = await db.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.workspace_id == workspace_id,
            IntegrationCredential.scope_key == scope_key,
            IntegrationCredential.provider == provider,
            IntegrationCredential.external_account_id == external_account_id,
        )
    )
    if existing and existing.status != "revoked":
        raise IntegrationServiceError(
            "An integration already exists for this provider and scope. Rotate it instead.",
            409,
        )

    try:
        encrypted_payload, fingerprint = get_credential_vault().encrypt(normalized)
    except CredentialVaultError as exc:
        raise IntegrationServiceError(str(exc), 503) from exc

    now = datetime.now(timezone.utc)
    if existing:
        credential = existing
        credential.label = label
        credential.encrypted_payload = encrypted_payload
        credential.payload_fingerprint = fingerprint
        credential.credential_metadata = safe_metadata(provider, normalized)
        credential.status = "active"
        credential.last_validation_status = "not_tested"
        credential.last_validation_error = None
        credential.last_validated_at = None
        credential.rotated_at = now
        credential.revoked_at = None
        credential.updated_by_user_id = user_id
    else:
        credential = IntegrationCredential(
            workspace_id=workspace_id,
            site_id=site_id,
            scope_key=scope_key,
            provider=provider,
            label=label,
            external_account_id=external_account_id,
            encrypted_payload=encrypted_payload,
            payload_fingerprint=fingerprint,
            credential_metadata=safe_metadata(provider, normalized),
            status="active",
            last_validation_status="not_tested",
            created_by_user_id=user_id,
            updated_by_user_id=user_id,
        )
        db.add(credential)

    await db.commit()
    await db.refresh(credential)
    return integration_response(credential)


async def rotate_integration(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    credential_id: uuid.UUID,
    label: str | None,
    credentials: dict[str, Any],
) -> IntegrationCredentialResponse:
    credential = await get_integration(
        db, workspace_id=workspace_id, credential_id=credential_id
    )
    spec = _provider(credential.provider)
    await _require_site(
        db,
        workspace_id=workspace_id,
        site_id=credential.site_id,
        spec=spec,
    )
    normalized = validate_credentials(credential.provider, credentials)
    try:
        encrypted_payload, fingerprint = get_credential_vault().encrypt(normalized)
    except CredentialVaultError as exc:
        raise IntegrationServiceError(str(exc), 503) from exc

    credential.encrypted_payload = encrypted_payload
    credential.payload_fingerprint = fingerprint
    credential.credential_metadata = safe_metadata(credential.provider, normalized)
    credential.label = label or credential.label
    credential.status = "active"
    credential.last_validation_status = "not_tested"
    credential.last_validation_error = None
    credential.last_validated_at = None
    credential.rotated_at = datetime.now(timezone.utc)
    credential.revoked_at = None
    credential.updated_by_user_id = user_id
    await db.commit()
    await db.refresh(credential)
    return integration_response(credential)


async def revoke_integration(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    credential_id: uuid.UUID,
) -> None:
    credential = await get_integration(
        db, workspace_id=workspace_id, credential_id=credential_id
    )
    if credential.status == "revoked":
        return

    now = datetime.now(timezone.utc)
    try:
        encrypted_payload, fingerprint = get_credential_vault().encrypt(
            {"revoked": True, "revoked_at": now.isoformat()}
        )
    except CredentialVaultError as exc:
        raise IntegrationServiceError(str(exc), 503) from exc

    credential.encrypted_payload = encrypted_payload
    credential.payload_fingerprint = fingerprint
    credential.status = "revoked"
    credential.last_validation_status = "revoked"
    credential.last_validation_error = None
    credential.revoked_at = now
    credential.updated_by_user_id = user_id
    await db.commit()


def _openai_models_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    return f"{normalized}/models" if normalized.endswith("/v1") else f"{normalized}/v1/models"


async def _test_provider_connection(provider: str, payload: dict[str, Any]) -> tuple[str, str]:
    timeout = httpx.Timeout(10.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        if provider == "openai":
            headers = {"Authorization": f"Bearer {payload['api_key']}"}
            if payload.get("organization"):
                headers["OpenAI-Organization"] = payload["organization"]
            if payload.get("project"):
                headers["OpenAI-Project"] = payload["project"]
            response = await client.get(
                _openai_models_url(payload.get("base_url", "https://api.openai.com")),
                headers=headers,
            )
        elif provider == "gemini":
            response = await client.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                params={"key": payload["api_key"], "pageSize": 1},
            )
        elif provider == "serpapi":
            response = await client.get(
                "https://serpapi.com/account.json",
                params={"api_key": payload["api_key"]},
            )
        elif provider == "serper":
            response = await client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": payload["api_key"], "Content-Type": "application/json"},
                json={"q": "SERP Strategists", "num": 1},
            )
        elif provider == "wordpress":
            response = await client.get(
                f"{payload['url'].rstrip('/')}/wp-json/wp/v2/users/me",
                params={"context": "edit"},
                auth=(payload["username"], payload["application_password"]),
            )
        else:
            raise IntegrationServiceError("Connection testing is not supported for this provider")

    if 200 <= response.status_code < 300:
        return "connected", "Connection verified"
    if response.status_code in {401, 403}:
        return "failed", "The provider rejected the credential"
    if response.status_code == 429:
        return "limited", "The provider rate limit was reached during validation"
    return "failed", f"The provider returned HTTP {response.status_code}"


async def test_integration(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    credential_id: uuid.UUID,
) -> tuple[IntegrationCredentialResponse, str]:
    credential = await get_integration(
        db, workspace_id=workspace_id, credential_id=credential_id
    )
    if credential.status != "active":
        raise IntegrationServiceError("Revoked integrations cannot be tested", 409)

    spec = _provider(credential.provider)
    if not spec.test_supported:
        raise IntegrationServiceError("Connection testing is not supported for this provider")

    try:
        payload = get_credential_vault().decrypt(credential.encrypted_payload)
    except CredentialVaultError as exc:
        raise IntegrationServiceError(str(exc), 503) from exc

    tested_at = datetime.now(timezone.utc)
    try:
        validation_status, message = await _test_provider_connection(
            credential.provider, payload
        )
    except httpx.TimeoutException:
        validation_status, message = "failed", "The provider connection timed out"
    except httpx.HTTPError:
        validation_status, message = "failed", "The provider could not be reached"

    credential.last_validation_status = validation_status
    credential.last_validation_error = None if validation_status == "connected" else message
    credential.last_validated_at = tested_at
    await db.commit()
    await db.refresh(credential)
    return integration_response(credential), message
