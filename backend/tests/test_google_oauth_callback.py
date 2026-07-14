from fastapi.testclient import TestClient

from app.main import app
from app.routers import google_data
from app.services.credential_vault import CredentialVaultError
from app.services.google_data_service import GoogleDataServiceError


def _callback(client: TestClient):
    return client.get(
        "/integrations/google/callback",
        params={"code": "test-code", "state": "test-state"},
        follow_redirects=False,
    )


def test_callback_redirects_when_credential_vault_is_unavailable(monkeypatch) -> None:
    async def fail_callback(*args, **kwargs):
        del args, kwargs
        raise CredentialVaultError("Credential encryption key is not configured")

    monkeypatch.setattr(google_data, "complete_google_oauth", fail_callback)

    with TestClient(app) as client:
        response = _callback(client)

    assert response.status_code == 303
    assert "step=google" in response.headers["location"]
    assert "google_error=credential_encryption_unavailable" in response.headers["location"]


def test_callback_redirects_for_google_service_errors(monkeypatch) -> None:
    async def fail_callback(*args, **kwargs):
        del args, kwargs
        raise GoogleDataServiceError("Google token exchange failed", 400)

    monkeypatch.setattr(google_data, "complete_google_oauth", fail_callback)

    with TestClient(app) as client:
        response = _callback(client)

    assert response.status_code == 303
    assert "google_error=google_connection_failed" in response.headers["location"]


def test_callback_redirects_for_unexpected_errors(monkeypatch) -> None:
    async def fail_callback(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("database connection was interrupted")

    monkeypatch.setattr(google_data, "complete_google_oauth", fail_callback)

    with TestClient(app) as client:
        response = _callback(client)

    assert response.status_code == 303
    assert "google_error=internal_error" in response.headers["location"]
    assert "database" not in response.headers["location"]
