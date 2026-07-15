import asyncio
from datetime import date, timedelta
from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from app.database import async_session_factory, engine
from app.main import app
from app.models.google_data_connection import GoogleDataConnection
from app.models.search_performance import SearchAnalyticsMetric
from app.services import search_performance_service as service
from app.services.search_performance_service import (
    SearchPerformanceError,
    _action_uses_mutating_adapter,
    _fetch_search_rows,
    _page_url_key,
    _property_matches_site,
    _ranges_cover_window,
    classify_action_outcome,
    detect_opportunity_candidates,
    run_search_sync_worker_tick,
)


PASSWORD = "correct-horse-battery-staple"


async def _reset_database_pool_for_test_loop() -> None:
    # TestClient owns a fresh event loop. Drop idle connections created by
    # earlier TestClient loops without trying to close them from this loop.
    await engine.dispose(close=False)


def test_search_scope_and_page_keys_are_conservative() -> None:
    assert _property_matches_site("sc-domain:example.com", "www.example.com")
    assert _property_matches_site("https://www.example.com/", "example.com")
    assert not _property_matches_site("https://example.com/blog/", "example.com")
    assert _page_url_key("http://www.example.com/pricing/") == _page_url_key(
        "https://example.com/pricing"
    )
    assert not _action_uses_mutating_adapter(
        SimpleNamespace(execution_target={"adapter": "  Simulation "})
    )


class _Response:
    status_code = 200

    def __init__(self, payload: dict):
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _ScriptedClient:
    def __init__(self, payloads: list[dict]):
        self.payloads = list(payloads)
        self.requests: list[dict] = []

    async def post(self, url: str, **kwargs):
        del url
        self.requests.append(kwargs["json"])
        return _Response(self.payloads.pop(0))


def test_daily_cap_probe_distinguishes_exact_cap_from_truncation(monkeypatch) -> None:
    monkeypatch.setattr(service.settings, "search_sync_page_size", 2)
    monkeypatch.setattr(service.settings, "search_sync_max_rows", 2)
    metric_day = date(2026, 1, 2)
    two_rows = [{"keys": [metric_day.isoformat(), str(index), "https://example.com/"]} for index in range(2)]

    exact = _ScriptedClient([{"rows": two_rows}, {"rows": []}])
    rows = asyncio.run(
        _fetch_search_rows(exact, token="token", property_id="sc-domain:example.com", metric_date=metric_day)
    )
    assert rows == two_rows
    assert exact.requests[-1]["rowLimit"] == 1
    assert exact.requests[-1]["startRow"] == 2

    truncated = _ScriptedClient([{"rows": two_rows}, {"rows": [{"keys": []}]}])
    with pytest.raises(SearchPerformanceError) as caught:
        asyncio.run(
            _fetch_search_rows(
                truncated,
                token="token",
                property_id="sc-domain:example.com",
                metric_date=metric_day,
            )
        )
    assert caught.value.code == "daily_row_cap"
    assert caught.value.retryable is False


def test_provider_finalization_metadata_moves_the_safe_boundary() -> None:
    proposed = date(2026, 1, 10)
    client = _ScriptedClient(
        [{"metadata": {"first_incomplete_date": "2026-01-09"}}]
    )
    finalized = asyncio.run(
        service._resolve_finalized_end_date(
            client,
            token="token",
            property_id="sc-domain:example.com",
            proposed_end=proposed,
        )
    )
    assert finalized == date(2026, 1, 8)


def test_measurement_coverage_composes_adjacent_completed_ranges() -> None:
    start = date(2026, 1, 1)
    end = date(2026, 1, 10)
    assert _ranges_cover_window(
        [(date(2026, 1, 1), date(2026, 1, 5)), (date(2026, 1, 6), end)],
        start=start,
        end=end,
    )
    assert not _ranges_cover_window(
        [(date(2026, 1, 1), date(2026, 1, 4)), (date(2026, 1, 6), end)],
        start=start,
        end=end,
    )


def _metric(day: date, query: str, page: str, *, clicks: float, impressions: float, position: float):
    return SimpleNamespace(
        metric_date=day,
        query=query,
        page_url=page,
        clicks=clicks,
        impressions=impressions,
        ctr=clicks / impressions if impressions else 0,
        position=position,
    )


def test_opportunity_detectors_cover_ctr_page_two_decay_and_cannibalization() -> None:
    end = date.today() - timedelta(days=1)
    rows = []
    for offset in range(28):
        day = end - timedelta(days=offset)
        rows.append(_metric(day, "low ctr", "https://example.com/a", clicks=0, impressions=10, position=4))
        rows.append(_metric(day, "page two", "https://example.com/b", clicks=1, impressions=10, position=14))
        rows.append(_metric(day, "competing", "https://example.com/a", clicks=1, impressions=4, position=8))
        rows.append(_metric(day, "competing", "https://example.com/b", clicks=1, impressions=4, position=9))
        rows.append(
            _metric(
                day,
                "declining",
                "https://example.com/c",
                clicks=0 if offset < 14 else 2,
                impressions=20,
                position=6,
            )
        )

    detected = detect_opportunity_candidates(rows, period_end=end)
    kinds = {item.opportunity_type for item in detected}
    assert {"low_ctr", "striking_distance", "traffic_decay", "cannibalization"} <= kinds


def test_outcome_classifier_enforces_data_floor_and_direction() -> None:
    assert classify_action_outcome(
        {"clicks": 1, "impressions": 10, "ctr": 0.1},
        {"clicks": 4, "impressions": 15, "ctr": 0.26},
    )[0] == "insufficient_data"
    assert classify_action_outcome(
        {"clicks": 20, "impressions": 200, "ctr": 0.10},
        {"clicks": 30, "impressions": 210, "ctr": 0.143},
    )[0] == "positive"
    assert classify_action_outcome(
        {"clicks": 30, "impressions": 200, "ctr": 0.15},
        {"clicks": 20, "impressions": 190, "ctr": 0.105},
    )[0] == "negative"


def test_durable_search_sync_persists_rows_and_opportunities(monkeypatch) -> None:
    suffix = uuid.uuid4().hex
    with TestClient(app) as client:
        assert client.portal is not None
        client.portal.call(_reset_database_pool_for_test_loop)
        registration = client.post(
            "/auth/register",
            json={
                "email": f"gsc-{suffix}@example.com",
                "password": PASSWORD,
                "name": "GSC Owner",
                "workspace_name": f"GSC {suffix}",
            },
        )
        assert registration.status_code == 201, registration.text
        auth = registration.json()
        headers = {
            "Authorization": f"Bearer {auth['access_token']}",
            "X-Workspace-ID": auth["workspace"]["id"],
        }
        created_site = client.post(
            "/sites",
            headers=headers,
            json={"domain": f"gsc-{suffix}.example.com", "name": "GSC Site"},
        )
        assert created_site.status_code == 201, created_site.text
        site_id = created_site.json()["id"]

        async def configure() -> None:
            async with async_session_factory() as db:
                db.add(
                    GoogleDataConnection(
                        workspace_id=uuid.UUID(auth["workspace"]["id"]),
                        user_id=uuid.UUID(auth["user"]["id"]),
                        status="configured",
                        gsc_property=f"sc-domain:gsc-{suffix}.example.com",
                    )
                )
                await db.commit()

        client.portal.call(configure)

        async def fake_rows(client, *, token, property_id, metric_date):
            del client, token, property_id
            return [{
                "keys": [metric_date.isoformat(), "valuable query", f"https://gsc-{suffix}.example.com/landing"],
                "clicks": 0,
                "impressions": 10,
                "ctr": 0,
                "position": 4,
            }]

        async def fake_token(db, connection):
            del db, connection
            return "test-token"

        async def fake_finalized_end(client, *, token, property_id, proposed_end):
            del client, token, property_id
            return proposed_end

        monkeypatch.setattr(service, "_fetch_search_rows", fake_rows)
        monkeypatch.setattr(service, "_access_token", fake_token)
        monkeypatch.setattr(service, "_resolve_finalized_end_date", fake_finalized_end)
        queued = client.post(f"/integrations/google-data/search-sync/{site_id}", headers=headers)
        assert queued.status_code == 202, queued.text
        job_id = queued.json()["id"]

        processed = client.portal.call(run_search_sync_worker_tick)
        assert processed == 1
        status = client.get(f"/integrations/google-data/search-sync/jobs/{job_id}", headers=headers)
        assert status.status_code == 200, status.text
        assert status.json()["status"] == "completed"
        assert status.json()["result"]["rows"] == service.settings.search_sync_lookback_days

        opportunities = client.get(f"/integrations/google-data/opportunities/{site_id}", headers=headers)
        assert opportunities.status_code == 200, opportunities.text
        assert opportunities.json()["total"] >= 1
        assert "low_ctr" in {item["opportunity_type"] for item in opportunities.json()["items"]}

        latest = client.get(
            f"/integrations/google-data/search-sync/sites/{site_id}/latest",
            headers=headers,
        )
        assert latest.status_code == 200, latest.text
        assert latest.json()["id"] == job_id
        assert latest.json()["status"] == "completed"

        action_queue = client.get(f"/operator-actions?site_id={site_id}", headers=headers)
        assert action_queue.status_code == 200, action_queue.text
        search_actions = [
            item
            for item in action_queue.json()["items"]
            if item["source"] == "gsc_opportunity_pipeline"
        ]
        assert search_actions
        assert all(item["status"] == "draft" for item in search_actions)
        assert all(item["execution_target"]["adapter"] == "simulation" for item in search_actions)

        detected_again = client.post(
            f"/integrations/google-data/opportunities/{site_id}/detect",
            headers=headers,
        )
        assert detected_again.status_code == 200, detected_again.text
        action_queue_again = client.get(f"/operator-actions?site_id={site_id}", headers=headers)
        assert action_queue_again.json()["total"] == action_queue.json()["total"]

        reused = client.post(f"/integrations/google-data/search-sync/{site_id}", headers=headers)
        assert reused.status_code == 200, reused.text
        assert reused.json()["reused"] is True
        assert reused.json()["id"] == job_id

        async def no_candidates(db, *, site_id, period_end):
            del db, site_id, period_end
            return []

        monkeypatch.setattr(service, "_detect_opportunity_candidates_from_db", no_candidates)
        resolved = client.post(
            f"/integrations/google-data/opportunities/{site_id}/detect",
            headers=headers,
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["total"] == 0
        resolved_queue = client.get(f"/operator-actions?site_id={site_id}", headers=headers)
        resolved_actions = [
            item
            for item in resolved_queue.json()["items"]
            if item["source"] == "gsc_opportunity_pipeline"
        ]
        assert resolved_actions
        assert all(item["status"] == "cancelled" for item in resolved_actions)


def test_total_cap_fails_once_rolls_back_and_enforces_cooldown(monkeypatch) -> None:
    suffix = uuid.uuid4().hex
    monkeypatch.setattr(service.settings, "search_sync_max_total_rows", 1)
    with TestClient(app) as client:
        assert client.portal is not None
        client.portal.call(_reset_database_pool_for_test_loop)
        registration = client.post(
            "/auth/register",
            json={
                "email": f"gsc-cap-{suffix}@example.com",
                "password": PASSWORD,
                "name": "GSC Cap Owner",
                "workspace_name": f"GSC Cap {suffix}",
            },
        )
        assert registration.status_code == 201, registration.text
        auth = registration.json()
        headers = {
            "Authorization": f"Bearer {auth['access_token']}",
            "X-Workspace-ID": auth["workspace"]["id"],
        }
        domain = f"gsc-cap-{suffix}.example.com"
        created_site = client.post(
            "/sites",
            headers=headers,
            json={"domain": domain, "name": "GSC Cap Site"},
        )
        assert created_site.status_code == 201, created_site.text
        site_id = created_site.json()["id"]

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

        async def fake_rows(client, *, token, property_id, metric_date):
            del client, token, property_id
            return [{
                "keys": [metric_date.isoformat(), "high-cardinality", f"https://{domain}/page"],
                "clicks": 0,
                "impressions": 1,
                "ctr": 0,
                "position": 5,
            }]

        async def fake_token(db, connection):
            del db, connection
            return "test-token"

        async def fake_finalized_end(client, *, token, property_id, proposed_end):
            del client, token, property_id
            return proposed_end

        async def count_metrics() -> int:
            async with async_session_factory() as db:
                return int(
                    await db.scalar(
                        select(func.count())
                        .select_from(SearchAnalyticsMetric)
                        .where(SearchAnalyticsMetric.site_id == uuid.UUID(site_id))
                    )
                    or 0
                )

        client.portal.call(configure)
        monkeypatch.setattr(service, "_fetch_search_rows", fake_rows)
        monkeypatch.setattr(service, "_access_token", fake_token)
        monkeypatch.setattr(service, "_resolve_finalized_end_date", fake_finalized_end)

        queued = client.post(f"/integrations/google-data/search-sync/{site_id}", headers=headers)
        assert queued.status_code == 202, queued.text
        processed = client.portal.call(run_search_sync_worker_tick)
        assert processed == 1

        status_response = client.get(
            f"/integrations/google-data/search-sync/jobs/{queued.json()['id']}",
            headers=headers,
        )
        assert status_response.status_code == 200, status_response.text
        failed = status_response.json()
        assert failed["status"] == "failed"
        assert failed["attempt_count"] == 1
        assert failed["error_code"] == "job_row_cap"
        assert client.portal.call(count_metrics) == 0

        blocked = client.post(
            f"/integrations/google-data/search-sync/{site_id}",
            headers=headers,
        )
        assert blocked.status_code == 429, blocked.text
        assert int(blocked.headers["retry-after"]) > 0
