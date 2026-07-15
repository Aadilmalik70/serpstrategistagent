import asyncio
import base64
from datetime import datetime, timezone
import uuid
from urllib.parse import parse_qs, urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
import httpx
from jose import jwt
import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.database import engine
from app.main import app
from app.schemas.github_repository import GitHubRepositoryConnectRequest
from app.services import github_app_service as service


PASSWORD = "correct-horse-battery-staple"


async def _reset_database_pool_for_test_loop() -> None:
    await engine.dispose(close=False)


def _private_key() -> tuple[str, bytes]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return base64.b64encode(private_pem).decode("ascii"), public_pem


def _register(client: TestClient, email: str, workspace_name: str) -> dict:
    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": email.split("@", 1)[0],
            "workspace_name": workspace_name,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _headers(auth: dict) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {auth['access_token']}",
        "X-Workspace-ID": auth["workspace"]["id"],
    }


class _Response:
    def __init__(self, status_code: int, payload: object):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


class _ProviderClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    async def post(self, url: str, **kwargs) -> _Response:
        self.calls.append(("POST", url, kwargs))
        return _Response(201, {"token": "ephemeral-installation-token", "expires_at": "soon"})

    async def get(self, url: str, **kwargs) -> _Response:
        self.calls.append(("GET", url, kwargs))
        return _Response(
            200,
            {
                "repositories": [
                    {
                        "id": 101,
                        "full_name": "operator/private-site",
                        "private": True,
                        "visibility": "private",
                        "default_branch": "main",
                        "permissions": {"pull": True, "push": True},
                    }
                ]
            },
        )


class _FailingProviderClient:
    async def post(self, url: str, **_kwargs) -> _Response:
        raise httpx.ConnectTimeout("provider timeout", request=httpx.Request("POST", url))


def test_github_app_jwt_and_ephemeral_installation_token_contract() -> None:
    # Other provider tests intentionally clear the cached Settings object. The
    # GitHub App service must always use the current configured instance.
    get_settings.cache_clear()
    settings = get_settings()
    encoded_key, public_key = _private_key()
    previous = (
        settings.github_app_id,
        settings.github_app_slug,
        settings.github_app_private_key_base64,
    )
    settings.github_app_id = "123456"
    settings.github_app_slug = "serp-strategists-test"
    settings.github_app_private_key_base64 = encoded_key

    try:
        now = datetime.now(timezone.utc)
        app_token = service.build_github_app_jwt(now=now)
        claims = jwt.decode(app_token, public_key, algorithms=["RS256"])
        assert claims["iss"] == "123456"
        assert claims["iat"] == int(now.timestamp()) - 60
        assert claims["exp"] == int(now.timestamp()) + 540

        provider = _ProviderClient()
        repositories = asyncio.run(service.list_provider_repositories(789, client=provider))
        assert [repository["full_name"] for repository in repositories] == [
            "operator/private-site"
        ]
        assert provider.calls[0][0] == "POST"
        assert provider.calls[0][1].endswith("/app/installations/789/access_tokens")
        assert provider.calls[1][0] == "GET"
        assert provider.calls[1][1].endswith("/installation/repositories")
        assert (
            provider.calls[1][2]["headers"]["Authorization"]
            == "Bearer ephemeral-installation-token"
        )
        assert "ephemeral-installation-token" not in repr(repositories)
    finally:
        (
            settings.github_app_id,
            settings.github_app_slug,
            settings.github_app_private_key_base64,
        ) = previous


def test_repository_mapping_request_accepts_exactly_one_authorization_source() -> None:
    site_id = uuid.uuid4()
    installation_id = uuid.uuid4()
    public_mapping = GitHubRepositoryConnectRequest(
        site_id=site_id,
        repository="https://github.com/operator/public-site",
    )
    assert public_mapping.repository == "operator/public-site"

    app_mapping = GitHubRepositoryConnectRequest(
        site_id=site_id,
        installation_id=installation_id,
        repository_id=101,
    )
    assert app_mapping.installation_id == installation_id

    with pytest.raises(ValidationError):
        GitHubRepositoryConnectRequest(site_id=site_id, installation_id=installation_id)
    with pytest.raises(ValidationError):
        GitHubRepositoryConnectRequest(
            site_id=site_id,
            repository="operator/public-site",
            installation_id=installation_id,
            repository_id=101,
        )


def test_provider_transport_failures_are_retryable_and_sanitized() -> None:
    settings = get_settings()
    encoded_key, _ = _private_key()
    previous = (
        settings.github_app_id,
        settings.github_app_slug,
        settings.github_app_private_key_base64,
    )
    settings.github_app_id = "123456"
    settings.github_app_slug = "serp-strategists-test"
    settings.github_app_private_key_base64 = encoded_key
    try:
        with pytest.raises(service.GitHubAppError) as caught:
            asyncio.run(
                service.create_installation_token(789, client=_FailingProviderClient())
            )
        assert caught.value.code == "github_provider_unavailable"
        assert caught.value.retryable is True
        assert "provider timeout" not in str(caught.value)
    finally:
        (
            settings.github_app_id,
            settings.github_app_slug,
            settings.github_app_private_key_base64,
        ) = previous


def test_github_app_install_map_isolate_replay_and_disconnect(monkeypatch) -> None:
    suffix = uuid.uuid4().hex
    settings = get_settings()
    encoded_key, _ = _private_key()
    previous = (
        settings.github_app_id,
        settings.github_app_slug,
        settings.github_app_private_key_base64,
    )
    settings.github_app_id = "123456"
    settings.github_app_slug = "serp-strategists-test"
    settings.github_app_private_key_base64 = encoded_key

    async def fake_installation(installation_id: int, **_kwargs) -> dict:
        return {
            "id": installation_id,
            "account": {"id": 9001, "login": "operator-org", "type": "Organization"},
            "target_type": "Organization",
            "repository_selection": "selected",
            "permissions": {"contents": "write", "pull_requests": "write"},
            "suspended_at": None,
        }

    async def fake_repositories(installation_id: int, **_kwargs) -> list[dict]:
        assert installation_id == 7001
        return [
            {
                "id": 101,
                "full_name": "operator-org/private-site",
                "private": True,
                "visibility": "private",
                "default_branch": "main",
                "permissions": {"pull": True, "push": True, "admin": False},
            }
        ]

    monkeypatch.setattr(service, "fetch_provider_installation", fake_installation)
    monkeypatch.setattr(service, "list_provider_repositories", fake_repositories)

    try:
        with TestClient(app) as client:
            assert client.portal is not None
            client.portal.call(_reset_database_pool_for_test_loop)
            owner = _register(
                client,
                f"github-app-owner-{suffix}@example.com",
                f"GitHub App Owner {suffix}",
            )
            outsider = _register(
                client,
                f"github-app-outsider-{suffix}@example.com",
                f"GitHub App Outsider {suffix}",
            )
            owner_headers = _headers(owner)
            outsider_headers = _headers(outsider)

            site = client.post(
                "/sites",
                headers=owner_headers,
                json={"domain": f"github-app-{suffix}.example.com", "name": "Private Site"},
            )
            assert site.status_code == 201, site.text
            site_id = site.json()["id"]
            outsider_site = client.post(
                "/sites",
                headers=outsider_headers,
                json={
                    "domain": f"github-app-outsider-{suffix}.example.com",
                    "name": "Outsider Site",
                },
            )
            assert outsider_site.status_code == 201, outsider_site.text

            started = client.post("/integrations/github-app/start", headers=owner_headers)
            assert started.status_code == 200, started.text
            installation_url = started.json()["installation_url"]
            assert installation_url.startswith(
                "https://github.com/apps/serp-strategists-test/installations/new?"
            )
            state = parse_qs(urlparse(installation_url).query)["state"][0]

            callback = client.get(
                "/integrations/github-app/callback",
                params={"installation_id": 7001, "setup_action": "install", "state": state},
                follow_redirects=False,
            )
            assert callback.status_code == 303
            assert "github_app=connected" in callback.headers["location"]

            replay = client.get(
                "/integrations/github-app/callback",
                params={"installation_id": 7001, "setup_action": "install", "state": state},
                follow_redirects=False,
            )
            assert replay.status_code == 303
            assert "github_app_error=github_install_state_invalid" in replay.headers["location"]

            owner_status = client.get("/integrations/github-app/status", headers=owner_headers)
            assert owner_status.status_code == 200
            assert owner_status.json()["connected"] is True
            assert owner_status.json()["execution_enabled"] is False
            installation_record_id = owner_status.json()["installations"][0]["id"]

            outsider_status = client.get(
                "/integrations/github-app/status", headers=outsider_headers
            )
            assert outsider_status.status_code == 200
            assert outsider_status.json()["connected"] is False
            assert outsider_status.json()["installations"] == []

            repositories = client.get(
                "/integrations/github-app/repositories", headers=owner_headers
            )
            assert repositories.status_code == 200, repositories.text
            assert repositories.json()["items"][0]["full_name"] == "operator-org/private-site"
            assert repositories.json()["items"][0]["private"] is True

            outsider_mapping = client.post(
                "/integrations/github-repository",
                headers=outsider_headers,
                json={
                    "site_id": outsider_site.json()["id"],
                    "installation_id": installation_record_id,
                    "repository_id": 101,
                },
            )
            assert outsider_mapping.status_code == 404

            mapped = client.post(
                "/integrations/github-repository",
                headers=owner_headers,
                json={
                    "site_id": site_id,
                    "installation_id": installation_record_id,
                    "repository_id": 101,
                },
            )
            assert mapped.status_code == 200, mapped.text
            assert mapped.json()["authorization_source"] == "github_app"
            assert mapped.json()["authorization_ready"] is True
            assert mapped.json()["execution_ready"] is False
            assert mapped.json()["visibility"] == "private"

            disconnected = client.delete(
                f"/integrations/github-app/{installation_record_id}",
                headers=owner_headers,
            )
            assert disconnected.status_code == 204, disconnected.text

            repository_status = client.get(
                f"/integrations/github-repository/{site_id}", headers=owner_headers
            )
            assert repository_status.status_code == 200
            assert repository_status.json()["connected"] is False
            assert repository_status.json()["execution_ready"] is False
    finally:
        (
            settings.github_app_id,
            settings.github_app_slug,
            settings.github_app_private_key_base64,
        ) = previous
