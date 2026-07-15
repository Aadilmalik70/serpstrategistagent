import asyncio
from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient
import pytest

from app.database import async_session_factory, engine
from app.main import app
from app.models.google_data_connection import GoogleDataConnection
from app.services import url_inspection_service as service
from app.services.url_inspection_service import (
    UrlInspectionError,
    _canonical_inspection_url,
    _inspect_url,
    _inspection_candidates,
    run_url_inspection_worker_tick,
)


PASSWORD = "correct-horse-battery-staple"


async def _reset_database_pool_for_test_loop() -> None:
    await engine.dispose(close=False)


def test_inspection_urls_are_site_scoped_and_normalized() -> None:
    assert _canonical_inspection_url("example.com", "/pricing#plans") == "https://example.com/pricing"
    assert _canonical_inspection_url("https://example.com", "http://example.com/") == "http://example.com/"
    with pytest.raises(UrlInspectionError) as caught:
        _canonical_inspection_url("example.com", "https://attacker.example/pricing")
    assert caught.value.code == "invalid_inspection_scope"
    with pytest.raises(UrlInspectionError) as credentials:
        _canonical_inspection_url("example.com", "https://user:secret@example.com/pricing")
    assert credentials.value.code == "invalid_inspection_url"


def test_indexation_candidates_cover_blocking_missing_and_canonical_states() -> None:
    blocked = SimpleNamespace(
        inspection_url="https://example.com/blocked",
        verdict="FAIL",
        coverage_state="Blocked by robots.txt",
        robots_txt_state="DISALLOWED",
        indexing_state="BLOCKED_BY_ROBOTS_TXT",
        page_fetch_state="BLOCKED_ROBOTS_TXT",
        google_canonical=None,
        user_canonical=None,
    )
    assert _inspection_candidates(blocked)[0][0] == "indexation_blocked"

    missing = SimpleNamespace(
        inspection_url="https://example.com/missing",
        verdict="NEUTRAL",
        coverage_state="Discovered - currently not indexed",
        robots_txt_state="ALLOWED",
        indexing_state="INDEXING_ALLOWED",
        page_fetch_state="SUCCESSFUL",
        google_canonical=None,
        user_canonical=None,
    )
    assert _inspection_candidates(missing)[0][0] == "not_indexed"

    canonical = SimpleNamespace(
        inspection_url="https://example.com/preferred",
        verdict="PASS",
        coverage_state="Submitted and indexed",
        robots_txt_state="ALLOWED",
        indexing_state="INDEXING_ALLOWED",
        page_fetch_state="SUCCESSFUL",
        google_canonical="https://example.com/google",
        user_canonical="https://example.com/preferred",
    )
    assert _inspection_candidates(canonical)[0][0] == "canonical_mismatch"

    unspecified = SimpleNamespace(
        inspection_url="https://example.com/unknown",
        verdict="VERDICT_UNSPECIFIED",
        coverage_state=None,
        robots_txt_state="ROBOTS_TXT_STATE_UNSPECIFIED",
        indexing_state="INDEXING_STATE_UNSPECIFIED",
        page_fetch_state="PAGE_FETCH_STATE_UNSPECIFIED",
        google_canonical=None,
        user_canonical=None,
    )
    assert _inspection_candidates(unspecified) == []


class _Response:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _Client:
    def __init__(self, response: _Response):
        self.response = response
        self.request: dict | None = None

    async def post(self, url: str, **kwargs):
        self.request = {"url": url, **kwargs}
        return self.response


def test_url_inspection_provider_contract_and_retryability() -> None:
    client = _Client(_Response(200, {"inspectionResult": {"indexStatusResult": {"verdict": "PASS"}}}))
    result = asyncio.run(
        _inspect_url(
            client,
            token="token",
            property_id="sc-domain:example.com",
            inspection_url="https://example.com/",
        )
    )
    assert result["indexStatusResult"]["verdict"] == "PASS"
    assert client.request is not None
    assert client.request["json"] == {
        "inspectionUrl": "https://example.com/",
        "siteUrl": "sc-domain:example.com",
        "languageCode": "en-US",
    }

    rate_limited = _Client(_Response(429, {}))
    with pytest.raises(UrlInspectionError) as caught:
        asyncio.run(
            _inspect_url(
                rate_limited,
                token="token",
                property_id="sc-domain:example.com",
                inspection_url="https://example.com/",
            )
        )
    assert caught.value.retryable is True


def test_durable_url_inspection_creates_indexation_action(monkeypatch) -> None:
    suffix = uuid.uuid4().hex
    domain = f"inspection-{suffix}.example.com"
    with TestClient(app) as client:
        assert client.portal is not None
        client.portal.call(_reset_database_pool_for_test_loop)
        registration = client.post(
            "/auth/register",
            json={
                "email": f"inspection-{suffix}@example.com",
                "password": PASSWORD,
                "name": "Inspection Owner",
                "workspace_name": f"Inspection {suffix}",
            },
        )
        assert registration.status_code == 201, registration.text
        auth = registration.json()
        headers = {
            "Authorization": f"Bearer {auth['access_token']}",
            "X-Workspace-ID": auth["workspace"]["id"],
        }
        site = client.post(
            "/sites",
            headers=headers,
            json={"domain": domain, "name": "Inspection Site"},
        )
        assert site.status_code == 201, site.text
        site_id = site.json()["id"]

        async def configure() -> None:
            async with async_session_factory() as db:
                db.add(
                    GoogleDataConnection(
                        workspace_id=uuid.UUID(auth["workspace"]["id"]),
                        user_id=uuid.UUID(auth["user"]["id"]),
                        status="configured",
                        gsc_property=f"sc-domain:{domain}",
                    )
                )
                await db.commit()

        async def fake_token(db, connection):
            del db, connection
            return "test-token"

        async def fake_inspection(client, *, token, property_id, inspection_url):
            del client, token, property_id
            return {
                "indexStatusResult": {
                    "verdict": "FAIL",
                    "coverageState": "Crawled - currently not indexed",
                    "robotsTxtState": "ALLOWED",
                    "indexingState": "INDEXING_ALLOWED",
                    "pageFetchState": "SUCCESSFUL",
                    "lastCrawlTime": "2026-07-01T12:00:00Z",
                    "userCanonical": inspection_url,
                }
            }

        client.portal.call(configure)
        monkeypatch.setattr(service, "_access_token", fake_token)
        monkeypatch.setattr(service, "_inspect_url", fake_inspection)

        queued = client.post(
            f"/integrations/google-data/url-inspection/{site_id}",
            headers=headers,
            json={"urls": [f"https://{domain}/landing"]},
        )
        assert queued.status_code == 202, queued.text
        job_id = queued.json()["id"]
        assert client.portal.call(run_url_inspection_worker_tick) == 1

        status = client.get(
            f"/integrations/google-data/url-inspection/jobs/{job_id}",
            headers=headers,
        )
        assert status.status_code == 200, status.text
        assert status.json()["status"] == "completed"
        assert status.json()["result"]["processed"] == 1

        results = client.get(
            f"/integrations/google-data/url-inspection/results/{site_id}",
            headers=headers,
        )
        assert results.status_code == 200, results.text
        assert results.json()["total"] == 1
        assert results.json()["items"][0]["verdict"] == "FAIL"

        opportunities = client.get(
            f"/integrations/google-data/opportunities/{site_id}",
            headers=headers,
        )
        assert opportunities.status_code == 200, opportunities.text
        assert "not_indexed" in {
            item["opportunity_type"] for item in opportunities.json()["items"]
        }

        actions = client.get(f"/operator-actions?site_id={site_id}", headers=headers)
        assert actions.status_code == 200, actions.text
        generated = [
            item
            for item in actions.json()["items"]
            if item["source"] == "gsc_opportunity_pipeline"
        ]
        assert generated
        assert all(item["execution_target"]["adapter"] == "simulation" for item in generated)

        # Search Analytics reconciliation must not resolve URL Inspection opportunities.
        detected = client.post(
            f"/integrations/google-data/opportunities/{site_id}/detect",
            headers=headers,
        )
        assert detected.status_code == 200, detected.text
        assert "not_indexed" in {item["opportunity_type"] for item in detected.json()["items"]}

        reused = client.post(
            f"/integrations/google-data/url-inspection/{site_id}",
            headers=headers,
            json={"urls": []},
        )
        assert reused.status_code == 200, reused.text
        assert reused.json()["reused"] is True
        assert reused.json()["id"] == job_id
