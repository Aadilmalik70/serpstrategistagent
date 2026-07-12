import hashlib
import hmac
import json
import time
import uuid

from fastapi.testclient import TestClient
import pytest

from app.config import get_settings
from app.main import app
from app.services.billing_service import StripeBillingError, verify_stripe_signature
from app.services.entitlement_service import calendar_month_period, get_plan_entitlements


PASSWORD = "correct-horse-battery-staple"


def _register(client: TestClient, prefix: str) -> dict:
    unique = uuid.uuid4().hex[:10]
    response = client.post(
        "/auth/register",
        json={
            "email": f"{prefix}-{unique}@example.com",
            "password": PASSWORD,
            "name": prefix,
            "workspace_name": f"{prefix} {unique}",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _headers(auth: dict) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {auth['access_token']}",
        "X-Workspace-ID": auth["workspace"]["id"],
    }


def _stripe_signature(payload: bytes, secret: str, timestamp: int) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + payload,
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


def test_plan_entitlements_and_calendar_period() -> None:
    assert get_plan_entitlements("audit")["sites"] == 1
    assert get_plan_entitlements("growth")["sites"] == 5
    assert get_plan_entitlements("scale")["sites"] == 25

    period = calendar_month_period()
    assert period.start.day == 1
    assert period.start < period.end


def test_stripe_signature_verification_rejects_invalid_and_stale_signatures() -> None:
    payload = b'{"id":"evt_test"}'
    secret = "whsec_test_secret"
    now = int(time.time())

    verify_stripe_signature(payload, _stripe_signature(payload, secret, now), secret, now=now)

    with pytest.raises(StripeBillingError):
        verify_stripe_signature(payload, f"t={now},v1=invalid", secret, now=now)

    with pytest.raises(StripeBillingError):
        verify_stripe_signature(
            payload,
            _stripe_signature(payload, secret, now - 1000),
            secret,
            now=now,
        )


def test_audit_plan_enforces_site_and_collaborator_limits() -> None:
    with TestClient(app) as client:
        auth = _register(client, "quota-owner")
        headers = _headers(auth)

        plans = client.get("/billing/plans", headers=headers)
        assert plans.status_code == 200, plans.text
        assert [plan["id"] for plan in plans.json()] == ["audit", "growth", "scale"]

        summary = client.get("/billing/summary", headers=headers)
        assert summary.status_code == 200, summary.text
        assert summary.json()["plan"] == "audit"
        assert summary.json()["entitlements"]["sites"] == 1

        first_site = client.post(
            "/sites",
            headers=headers,
            json={"domain": f"first-{uuid.uuid4().hex}.example.com", "name": "First"},
        )
        assert first_site.status_code == 201, first_site.text

        second_site = client.post(
            "/sites",
            headers=headers,
            json={"domain": f"second-{uuid.uuid4().hex}.example.com", "name": "Second"},
        )
        assert second_site.status_code == 402, second_site.text
        assert second_site.json()["detail"]["code"] == "quota_exceeded"
        assert second_site.json()["detail"]["metric"] == "sites"

        first_invitation = client.post(
            "/workspaces/invitations",
            headers=headers,
            json={"email": f"member-{uuid.uuid4().hex}@example.com", "role": "member"},
        )
        assert first_invitation.status_code == 201, first_invitation.text

        second_invitation = client.post(
            "/workspaces/invitations",
            headers=headers,
            json={"email": f"member-{uuid.uuid4().hex}@example.com", "role": "member"},
        )
        assert second_invitation.status_code == 402, second_invitation.text
        assert second_invitation.json()["detail"]["metric"] == "team_members"


def test_signed_subscription_webhook_updates_plan_and_is_idempotent(monkeypatch) -> None:
    webhook_secret = "whsec_test_billing_webhook"
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", webhook_secret)
    monkeypatch.setenv("STRIPE_GROWTH_PRICE_ID", "price_growth_test")
    get_settings.cache_clear()

    try:
        with TestClient(app) as client:
            auth = _register(client, "stripe-owner")
            headers = _headers(auth)
            workspace_id = auth["workspace"]["id"]
            now = int(time.time())
            event = {
                "id": f"evt_{uuid.uuid4().hex}",
                "type": "customer.subscription.updated",
                "data": {
                    "object": {
                        "id": f"sub_{uuid.uuid4().hex}",
                        "object": "subscription",
                        "customer": f"cus_{uuid.uuid4().hex}",
                        "status": "active",
                        "cancel_at_period_end": False,
                        "current_period_start": now,
                        "current_period_end": now + 30 * 24 * 60 * 60,
                        "metadata": {"workspace_id": workspace_id, "plan": "growth"},
                        "items": {
                            "data": [
                                {
                                    "price": {"id": "price_growth_test"},
                                }
                            ]
                        },
                    }
                },
            }
            payload = json.dumps(event, separators=(",", ":")).encode("utf-8")
            signature = _stripe_signature(payload, webhook_secret, now)

            first = client.post(
                "/billing/webhook",
                content=payload,
                headers={"Stripe-Signature": signature, "Content-Type": "application/json"},
            )
            assert first.status_code == 200, first.text
            assert first.json() == {"received": True, "processed": True}

            duplicate = client.post(
                "/billing/webhook",
                content=payload,
                headers={"Stripe-Signature": signature, "Content-Type": "application/json"},
            )
            assert duplicate.status_code == 200, duplicate.text
            assert duplicate.json() == {"received": True, "processed": False}

            summary = client.get("/billing/summary", headers=headers)
            assert summary.status_code == 200, summary.text
            assert summary.json()["plan"] == "growth"
            assert summary.json()["status"] == "active"
            assert summary.json()["entitlements"]["sites"] == 5
            assert summary.json()["stripe_customer"] is True
    finally:
        get_settings.cache_clear()


def test_checkout_and_portal_urls_are_server_created(monkeypatch) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_server_only")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_server_only")
    monkeypatch.setenv("STRIPE_GROWTH_PRICE_ID", "price_growth_test")
    monkeypatch.setenv("STRIPE_SCALE_PRICE_ID", "price_scale_test")
    get_settings.cache_clear()

    from app.services import billing_service

    async def fake_stripe_request(method, path, *, data=None, client=None):
        del method, client
        if path == "customers":
            assert data and data["metadata[workspace_id]"]
            return {"id": "cus_test_checkout"}
        if path == "checkout/sessions":
            assert data and data["line_items[0][price]"] == "price_growth_test"
            return {"url": "https://checkout.stripe.com/test-session"}
        if path == "billing_portal/sessions":
            assert data and data["customer"] == "cus_test_checkout"
            return {"url": "https://billing.stripe.com/test-portal"}
        raise AssertionError(f"Unexpected Stripe path: {path}")

    monkeypatch.setattr(billing_service, "_stripe_request", fake_stripe_request)

    try:
        with TestClient(app) as client:
            auth = _register(client, "checkout-owner")
            headers = _headers(auth)

            checkout = client.post("/billing/checkout", headers=headers, json={"plan": "growth"})
            assert checkout.status_code == 200, checkout.text
            assert checkout.json()["url"] == "https://checkout.stripe.com/test-session"

            portal = client.post("/billing/portal", headers=headers)
            assert portal.status_code == 200, portal.text
            assert portal.json()["url"] == "https://billing.stripe.com/test-portal"
    finally:
        get_settings.cache_clear()
