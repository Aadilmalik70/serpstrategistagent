import hashlib
import hmac
import time
import uuid

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.schemas.auth import OAuthExchangeRequest
from app.services.oauth_service import oauth_signature_message


BRIDGE_SECRET = "ci-oauth-bridge-secret-with-more-than-thirty-two-characters"
PASSWORD = "correct-horse-battery-staple"


def _oauth_exchange(client: TestClient, data: dict) -> object:
    request = OAuthExchangeRequest(**data)
    timestamp = str(int(time.time()))
    signature = hmac.new(
        BRIDGE_SECRET.encode("utf-8"),
        oauth_signature_message(timestamp, request).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return client.post(
        "/auth/oauth/exchange",
        json=request.model_dump(),
        headers={
            "X-OAuth-Bridge-Timestamp": timestamp,
            "X-OAuth-Bridge-Signature": signature,
        },
    )


def test_oauth_provisions_and_reuses_verified_identity() -> None:
    settings = get_settings()
    previous_secret = settings.oauth_bridge_secret
    settings.oauth_bridge_secret = BRIDGE_SECRET
    suffix = uuid.uuid4().hex
    profile = {
        "provider": "google",
        "provider_account_id": f"google-{suffix}",
        "email": f"oauth-{suffix}@example.com",
        "email_verified": True,
        "name": "OAuth Owner",
        "image_url": "https://example.com/avatar.png",
    }

    try:
        with TestClient(app) as client:
            first = _oauth_exchange(client, profile)
            assert first.status_code == 200, first.text
            first_body = first.json()
            assert first_body["user"]["email"] == profile["email"]
            assert first_body["workspace"]["role"] == "owner"

            second = _oauth_exchange(client, profile)
            assert second.status_code == 200, second.text
            assert second.json()["user"]["id"] == first_body["user"]["id"]

            providers = client.get(
                "/auth/providers",
                headers={"Authorization": f"Bearer {second.json()['access_token']}"},
            )
            assert providers.status_code == 200
            assert providers.json()[0]["provider"] == "google"
    finally:
        settings.oauth_bridge_secret = previous_secret


def test_unverified_provider_email_is_rejected() -> None:
    settings = get_settings()
    previous_secret = settings.oauth_bridge_secret
    settings.oauth_bridge_secret = BRIDGE_SECRET
    suffix = uuid.uuid4().hex

    try:
        with TestClient(app) as client:
            response = _oauth_exchange(
                client,
                {
                    "provider": "google",
                    "provider_account_id": f"unverified-{suffix}",
                    "email": f"unverified-{suffix}@example.com",
                    "email_verified": False,
                    "name": "Unverified",
                },
            )
            assert response.status_code == 403
    finally:
        settings.oauth_bridge_secret = previous_secret


def test_existing_unverified_password_account_requires_confirmation() -> None:
    settings = get_settings()
    previous_secret = settings.oauth_bridge_secret
    settings.oauth_bridge_secret = BRIDGE_SECRET
    suffix = uuid.uuid4().hex
    email = f"link-{suffix}@example.com"
    profile = {
        "provider": "github",
        "provider_account_id": f"github-{suffix}",
        "email": email,
        "email_verified": True,
        "name": "Linked Owner",
    }

    try:
        with TestClient(app) as client:
            registered = client.post(
                "/auth/register",
                json={
                    "email": email,
                    "password": PASSWORD,
                    "name": "Password Owner",
                    "workspace_name": "Password Workspace",
                },
            )
            assert registered.status_code == 201, registered.text

            exchange = _oauth_exchange(client, profile)
            assert exchange.status_code == 200, exchange.text
            link_required = exchange.json()
            assert link_required["link_required"] is True
            assert link_required["email"] == email

            wrong_password = client.post(
                "/auth/oauth/link",
                json={"token": link_required["link_token"], "password": "wrong-password"},
            )
            assert wrong_password.status_code == 401

            linked = client.post(
                "/auth/oauth/link",
                json={"token": link_required["link_token"], "password": PASSWORD},
            )
            assert linked.status_code == 200, linked.text
            assert linked.json()["user"]["id"] == registered.json()["user"]["id"]

            reused = _oauth_exchange(client, profile)
            assert reused.status_code == 200, reused.text
            assert reused.json()["user"]["id"] == registered.json()["user"]["id"]

            replay = client.post(
                "/auth/oauth/link",
                json={"token": link_required["link_token"], "password": PASSWORD},
            )
            assert replay.status_code == 404
    finally:
        settings.oauth_bridge_secret = previous_secret
