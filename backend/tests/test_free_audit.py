import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.free_audit_service import FreeAuditServiceError, _validate_target, build_report


async def _noop_audit(*args, **kwargs):
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

        status = client.get(f"/public/audits/{payload['token']}")
        assert status.status_code == 200
        assert status.json()["token"] == payload["token"]

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
