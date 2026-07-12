import os
import uuid

from fastapi.testclient import TestClient

from app.main import app


PASSWORD = "correct-horse-battery-staple"
ENCRYPTION_KEY = "ci-credential-encryption-key-with-more-than-thirty-two-characters"


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


def _headers(auth: dict, workspace_id: str | None = None) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {auth['access_token']}",
        "X-Workspace-ID": workspace_id or auth["workspace"]["id"],
    }


def test_encrypted_integration_lifecycle_and_workspace_isolation(monkeypatch) -> None:
    previous_key = os.environ.get("CREDENTIAL_ENCRYPTION_KEY")
    os.environ["CREDENTIAL_ENCRYPTION_KEY"] = ENCRYPTION_KEY
    suffix = uuid.uuid4().hex

    async def fake_connection_test(provider: str, payload: dict) -> tuple[str, str]:
        assert provider == "openai"
        assert payload["api_key"] == "sk-test-secret-one"
        return "connected", "Connection verified"

    monkeypatch.setattr(
        "app.services.integration_service._test_provider_connection",
        fake_connection_test,
    )

    try:
        with TestClient(app) as client:
            owner = _register(client, f"integration-owner-{suffix}@example.com", "Integration Owner")
            outsider = _register(client, f"integration-outsider-{suffix}@example.com", "Outsider")
            owner_headers = _headers(owner)

            catalog = client.get("/integrations/providers", headers=owner_headers)
            assert catalog.status_code == 200
            providers = {item["id"]: item for item in catalog.json()}
            assert providers["openai"]["available"] is True
            assert providers["google_search_console"]["connection_mode"] == "oauth"
            assert providers["google_search_console"]["available"] is False

            created = client.post(
                "/integrations",
                headers=owner_headers,
                json={
                    "provider": "openai",
                    "label": "Primary OpenAI",
                    "external_account_id": "default",
                    "credentials": {
                        "api_key": "sk-test-secret-one",
                        "organization": "org-test",
                    },
                },
            )
            assert created.status_code == 201, created.text
            credential = created.json()
            credential_id = credential["id"]
            assert credential["provider"] == "openai"
            assert credential["metadata"]["secret_hint"] == "••••-one"
            assert credential["metadata"]["organization"] == "org-test"
            assert "api_key" not in credential
            assert "credentials" not in credential
            assert "encrypted_payload" not in credential
            assert "sk-test-secret-one" not in created.text

            duplicate = client.post(
                "/integrations",
                headers=owner_headers,
                json={
                    "provider": "openai",
                    "label": "Duplicate",
                    "credentials": {"api_key": "sk-duplicate"},
                },
            )
            assert duplicate.status_code == 409

            listed = client.get("/integrations", headers=owner_headers)
            assert listed.status_code == 200
            assert len(listed.json()) == 1
            assert "sk-test-secret-one" not in listed.text

            outsider_list = client.get("/integrations", headers=_headers(outsider))
            assert outsider_list.status_code == 200
            assert outsider_list.json() == []

            outsider_rotate = client.put(
                f"/integrations/{credential_id}",
                headers=_headers(outsider),
                json={"credentials": {"api_key": "sk-outsider"}},
            )
            assert outsider_rotate.status_code == 404

            tested = client.post(
                f"/integrations/{credential_id}/test",
                headers=owner_headers,
            )
            assert tested.status_code == 200, tested.text
            assert tested.json()["status"] == "connected"

            rotated = client.put(
                f"/integrations/{credential_id}",
                headers=owner_headers,
                json={
                    "label": "Rotated OpenAI",
                    "credentials": {"api_key": "sk-test-secret-two"},
                },
            )
            assert rotated.status_code == 200, rotated.text
            assert rotated.json()["label"] == "Rotated OpenAI"
            assert rotated.json()["metadata"]["secret_hint"] == "••••-two"
            assert rotated.json()["last_validation_status"] == "not_tested"
            assert "sk-test-secret-two" not in rotated.text

            revoked = client.delete(
                f"/integrations/{credential_id}",
                headers=owner_headers,
            )
            assert revoked.status_code == 204

            active_after_revoke = client.get("/integrations", headers=owner_headers)
            assert active_after_revoke.status_code == 200
            assert active_after_revoke.json() == []

            all_after_revoke = client.get(
                "/integrations?include_revoked=true",
                headers=owner_headers,
            )
            assert all_after_revoke.status_code == 200
            assert all_after_revoke.json()[0]["status"] == "revoked"
            assert "sk-test-secret-one" not in all_after_revoke.text
            assert "sk-test-secret-two" not in all_after_revoke.text

            reconnected = client.post(
                "/integrations",
                headers=owner_headers,
                json={
                    "provider": "openai",
                    "label": "Reconnected OpenAI",
                    "credentials": {"api_key": "sk-test-secret-three"},
                },
            )
            assert reconnected.status_code == 201, reconnected.text
            assert reconnected.json()["id"] == credential_id
            assert reconnected.json()["status"] == "active"
    finally:
        if previous_key is None:
            os.environ.pop("CREDENTIAL_ENCRYPTION_KEY", None)
        else:
            os.environ["CREDENTIAL_ENCRYPTION_KEY"] = previous_key


def test_wordpress_requires_a_site_in_the_same_workspace() -> None:
    previous_key = os.environ.get("CREDENTIAL_ENCRYPTION_KEY")
    os.environ["CREDENTIAL_ENCRYPTION_KEY"] = ENCRYPTION_KEY
    suffix = uuid.uuid4().hex

    try:
        with TestClient(app) as client:
            owner = _register(client, f"wordpress-owner-{suffix}@example.com", "WordPress Owner")
            outsider = _register(client, f"wordpress-outsider-{suffix}@example.com", "WordPress Outsider")
            owner_headers = _headers(owner)

            missing_site = client.post(
                "/integrations",
                headers=owner_headers,
                json={
                    "provider": "wordpress",
                    "label": "WordPress",
                    "credentials": {
                        "url": "https://example.com",
                        "username": "operator",
                        "application_password": "application-password",
                    },
                },
            )
            assert missing_site.status_code == 400

            outsider_site = client.post(
                "/sites",
                headers=_headers(outsider),
                json={
                    "domain": f"wordpress-{suffix}.example.com",
                    "name": "Outsider WordPress",
                },
            )
            assert outsider_site.status_code == 201, outsider_site.text

            cross_workspace = client.post(
                "/integrations",
                headers=owner_headers,
                json={
                    "provider": "wordpress",
                    "label": "Cross workspace",
                    "site_id": outsider_site.json()["id"],
                    "credentials": {
                        "url": "https://example.com",
                        "username": "operator",
                        "application_password": "application-password",
                    },
                },
            )
            assert cross_workspace.status_code == 404
    finally:
        if previous_key is None:
            os.environ.pop("CREDENTIAL_ENCRYPTION_KEY", None)
        else:
            os.environ["CREDENTIAL_ENCRYPTION_KEY"] = previous_key
