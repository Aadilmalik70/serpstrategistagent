from datetime import datetime, timezone
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import async_session_factory
from app.main import app
from app.models.free_audit import FreeAuditRequest
from app.services.free_audit_service import FreeAuditServiceError, _validate_target, build_report


PASSWORD = "correct-horse-battery-staple"


async def _noop_audit(*args, **kwargs):
    del args, kwargs


async def _noop_crawl(*args, **kwargs):
    del args, kwargs


def test_public_free_audit_create_status_and_dedup(monkeypatch) -> None:
    monkeypatch.setattr("app.routers.public_audits.execute_free_audit", _noop_audit)
    suffix = uuid.uuid4().hex
    email = f"audit-{suffix}@example.com"

    with TestClient(app) as client:
        created = client.post(
            "/public/audits",
            json={"email": email, "website": f"example-{suffix}.com"},
        )
        assert created.status_code == 202, created.text
        payload = created.json()
        assert payload["status"] == "queued"
        assert payload["website"].startswith("https://")
        assert payload["score"] is None
        assert "email" not in payload
        assert "requester_hash" not in payload
        assert len(payload["token"]) >= 20

        status_response = client.get(f"/public/audits/{payload['token']}")
        assert status_response.status_code == 200
        assert status_response.json()["token"] == payload["token"]

        duplicate = client.post(
            "/public/audits",
            json={"email": email, "website": f"https://example-{suffix}.com"},
        )
        assert duplicate.status_code == 202
        assert duplicate.json()["token"] == payload["token"]


def test_public_free_audit_validates_input(monkeypatch) -> None:
    monkeypatch.setattr("app.routers.public_audits.execute_free_audit", _noop_audit)
    with TestClient(app) as client:
        invalid_email = client.post(
            "/public/audits",
            json={"email": "not-an-email", "website": "example.com"},
        )
        assert invalid_email.status_code == 422

        invalid_url = client.post(
            "/public/audits",
            json={"email": "valid@example.com", "website": "http://"},
        )
        assert invalid_url.status_code == 422


@pytest.mark.asyncio
async def test_completed_free_audit_claim_is_authenticated_tenant_safe_and_idempotent(monkeypatch) -> None:
    monkeypatch.setattr("app.routers.public_audits.execute_free_audit", _noop_audit)
    monkeypatch.setattr("app.routers.crawl.run_crawl_job", _noop_crawl)
    suffix = uuid.uuid4().hex
    domain = f"claim-{suffix}.example.com"
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        created = await client.post(
            "/public/audits",
            json={"email": f"claim-{suffix}@example.com", "website": domain},
        )
        assert created.status_code == 202, created.text
        token = created.json()["token"]

        anonymous = await client.post(f"/public/audits/{token}/claim")
        assert anonymous.status_code == 401

        owner_response = await client.post(
            "/auth/register",
            json={
                "email": f"claim-owner-{suffix}@example.com",
                "password": PASSWORD,
                "name": "Claim Owner",
                "workspace_name": "Claim Workspace",
            },
        )
        outsider_response = await client.post(
            "/auth/register",
            json={
                "email": f"claim-outsider-{suffix}@example.com",
                "password": PASSWORD,
                "name": "Claim Outsider",
                "workspace_name": "Claim Outsider Workspace",
            },
        )
        assert owner_response.status_code == 201, owner_response.text
        assert outsider_response.status_code == 201, outsider_response.text
        owner = owner_response.json()
        outsider = outsider_response.json()
        owner_headers = {
            "Authorization": f"Bearer {owner['access_token']}",
            "X-Workspace-ID": owner["workspace"]["id"],
        }
        outsider_headers = {
            "Authorization": f"Bearer {outsider['access_token']}",
            "X-Workspace-ID": outsider["workspace"]["id"],
        }

        not_ready = await client.post(f"/public/audits/{token}/claim", headers=owner_headers)
        assert not_ready.status_code == 409

        async with async_session_factory() as db:
            audit = await db.scalar(
                select(FreeAuditRequest).where(FreeAuditRequest.public_token == token)
            )
            assert audit is not None
            audit.status = "completed"
            audit.score = 90
            audit.completed_at = datetime.now(timezone.utc)
            await db.commit()

        claimed = await client.post(f"/public/audits/{token}/claim", headers=owner_headers)
        assert claimed.status_code == 202, claimed.text
        payload = claimed.json()
        assert payload["domain"] == domain
        assert payload["crawl_status"] == "queued"
        assert payload["reused_site"] is False
        assert payload["reused_crawl"] is False

        repeated = await client.post(f"/public/audits/{token}/claim", headers=owner_headers)
        assert repeated.status_code == 202, repeated.text
        assert repeated.json()["site_id"] == payload["site_id"]
        assert repeated.json()["crawl_job_id"] == payload["crawl_job_id"]
        assert repeated.json()["reused_site"] is True
        assert repeated.json()["reused_crawl"] is True

        cross_tenant = await client.post(
            f"/public/audits/{token}/claim",
            headers=outsider_headers,
        )
        assert cross_tenant.status_code == 409

        site = await client.get(f"/sites/{payload['site_id']}", headers=owner_headers)
        assert site.status_code == 200, site.text
        assert site.json()["domain"] == domain
        assert site.json()["status"] == "crawl_queued"

        async with async_session_factory() as db:
            audit = await db.scalar(
                select(FreeAuditRequest).where(FreeAuditRequest.public_token == token)
            )
            assert audit is not None
            assert str(audit.claimed_workspace_id) == owner["workspace"]["id"]
            assert str(audit.claimed_site_id) == payload["site_id"]
            assert audit.claimed_at is not None


def test_build_report_prioritizes_material_findings() -> None:
    html = b"""
    <html>
      <head>
        <title>Too short</title>
        <meta name="robots" content="noindex,follow">
      </head>
      <body><h1>One</h1><h1>Two</h1></body>
    </html>
    """
    score, summary, findings = build_report(
        requested_url="http://example.com",
        final_url="http://example.com",
        status_code=200,
        headers={"content-type": "text/html; charset=utf-8"},
        body=html,
        response_time_ms=3200,
        robots_status=404,
        sitemap_status=404,
    )

    assert score < 50
    assert summary["h1_count"] == 2
    assert summary["http_status"] == 200
    assert findings[0]["severity"] == "critical"
    assert {item["code"] for item in findings} >= {
        "noindex",
        "https_missing",
        "description_missing",
        "canonical_missing",
        "sitemap_missing",
        "slow_response",
    }


@pytest.mark.asyncio
async def test_private_network_targets_are_blocked() -> None:
    with pytest.raises(FreeAuditServiceError):
        await _validate_target("http://127.0.0.1:8000/internal")
