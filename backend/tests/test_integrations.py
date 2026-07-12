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


def _wordpress_credentials(password: str) -> dict[str, str]:
    return {
        "url": "https://example.com",
        "username": "operator",
        "application_password": password,
    }


def test_encrypted_integration_lifecycle_and_workspace_isolation(monkeypatch) -> None:
    previous_key = os.environ.get("CREDENTIAL_ENCRYPTION_KEY")
    os.environ["CREDENTIAL_ENCRYPTION_KEY"] = ENCRYPTION_KEY
    suffix = uuid.uuid4().hex

    async def fake_connection_test(provider: str, payload: dict) -> tuple[str, str]:
        assert provider == "wordpress"
        assert payload["application_password"] == "application-password-one"
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
            assert set(providers) == {"wordpress"}
            assert providers["wordpress"]["available"] is True
            for dedicated_provider in ("google_search_console", "google_analytics"):
                assert dedicated_provider not in providers
            for platform_provider in ("openai", "gemini", "serpapi", "serper", "ai_gateway"):
                assert platform_provider not in providers

            site = client.post(
                "/sites",
                headers=owner_headers,
                json={
                    "domain": f"wordpress-{suffix}.example.com",
                    "name": "Owner WordPress",
                },
            )
            assert site.status_code == 201, site.text
            site_id = site.json()["id"]

            created = client.post(
                "/integrations",
                headers=owner_headers,
                json={
                    "provider": "wordpress",
                    "label": "Primary WordPress",
                    "site_id": site_id,
                    "external_account_id": "default",
                    "credentials": _wordpress_credentials("application-password-one"),
                },
            )
            assert created.status_code == 201, created.text
            credential = created.json()
            credential_id = credential["id"]
            assert credential["provider"] == "wordpress"
            assert credential["metadata"]["secret_hint"] == "••••-one"
            assert credential["metadata"]["url"] == "https://example.com"
            assert credential["metadata"]["username"] == "operator"
            assert "credentials" not in credential
            assert "encrypted_payload" not in credential
            assert "application-password-one" not in created.text

            duplicate = client.post(
                "/integrations",
                headers=owner_headers,
                json={
                    "provider": "wordpress",
                    "label": "Duplicate",
                    "site_id": site_id,
                    "credentials": _wordpress_credentials("duplicate-password"),
                },
            )
            assert duplicate.status_code == 409

            for platform_provider in ("openai", "gemini", "serpapi", "serper", "ai_gateway"):
                rejected = client.post(
                    "/integrations",
                    headers=owner_headers,
                    json={
                        "provider": platform_provider,
                        "label": f"Forbidden {platform_provider}",
                        "credentials": {"api_key": "should-never-be-stored"},
                    },
                )
                assert rejected.status_code == 422
                assert "should-never-be-stored" not in rejected.text

            listed = client.get("/integrations", headers=owner_headers)
            assert listed.status_code == 200
            assert len(listed.json()) == 1
            assert "application-password-one" not in listed.text

            outsider_list = client.get("/integrations", headers=_headers(outsider))
            assert outsider_list.status_code == 200
            assert outsider_list.json() == []

            outsider_rotate = client.put(
                f"/integrations/{credential_id}",
                headers=_headers(outsider),
                json={"credentials": _wordpress_credentials("outsider-password")},
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
                    "label": "Rotated WordPress",
                    "credentials": _wordpress_credentials("application-password-two"),
                },
            )
            assert rotated.status_code == 200, rotated.text
            assert rotated.json()["label"] == "Rotated WordPress"
            assert rotated.json()["metadata"]["secret_hint"] == "••••-two"
            assert rotated.json()["last_validation_status"] == "not_tested"
            assert "application-password-two" not in rotated.text

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
            assert "application-password-one" not in all_after_revoke.text
            assert "application-password-two" not in all_after_revoke.text

            reconnected = client.post(
                "/integrations",
                headers=owner_headers,
                json={
                    "provider": "wordpress",
                    "label": "Reconnected WordPress",
                    "site_id": site_id,
                    "credentials": _wordpress_credentials("application-password-three"),
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
                    "credentials": _wordpress_credentials("application-password"),
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
                    "credentials": _wordpress_credentials("application-password"),
                },
            )
            assert cross_workspace.status_code == 404
    finally:
        if previous_key is None:
            os.environ.pop("CREDENTIAL_ENCRYPTION_KEY", None)
        else:
            os.environ["CREDENTIAL_ENCRYPTION_KEY"] = previous_key
