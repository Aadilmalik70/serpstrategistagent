from datetime import datetime, timezone
import uuid
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import async_session_factory
from app.main import app
from app.models.agent_run import AgentRun
from app.models.job_queue import JobQueue
from app.models.page import Page
from app.services import first_party_crawler as crawler
from app.services import crawl_job_service
from app.services.crawl_job_service import run_crawl_worker_tick
from app.services.first_party_crawler import CrawlError, FetchResult


PASSWORD = "correct-horse-battery-staple"


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


def _create_site(client: TestClient, auth: dict, domain: str) -> str:
    response = client.post(
        "/sites",
        headers=_headers(auth),
        json={"domain": domain, "name": "Agent Crawl Test"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _result(url: str, body: str, content_type: str = "text/html") -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        status_code=200,
        headers={"content-type": content_type},
        body=body.encode("utf-8"),
        response_time_ms=10,
        redirect_chain=[],
        truncated=False,
    )


def test_agent_crawls_before_analysis_when_site_has_no_pages(monkeypatch) -> None:
    suffix = uuid.uuid4().hex
    domain = f"agent-crawl-{suffix}.example.com"

    async def fake_fetch(client, url: str, **kwargs):
        del client, kwargs
        path = urlsplit(url).path
        if path == "/robots.txt":
            return _result(url, "User-agent: *\n", "text/plain")
        if path == "/sitemap.xml":
            return _result(url, "<urlset></urlset>", "application/xml")
        if path == "/":
            return _result(
                url,
                "<html><head><title>Agent crawl home</title></head><body><h1>Home</h1></body></html>",
            )
        raise AssertionError(f"Unexpected URL: {url}")

    async def fake_agent_graph(
        site_id: uuid.UUID,
        run_id: uuid.UUID,
        **kwargs,
    ):
        del kwargs
        async with async_session_factory() as db:
            pages = int(
                await db.scalar(select(func.count(Page.id)).where(Page.site_id == site_id)) or 0
            )
            run = await db.get(AgentRun, run_id)
            assert run is not None
            assert pages == 1
            run.status = "completed"
            run.pages_analyzed = pages
            run.issues_found = 0
            run.summary = "Analyzed 1 crawled page."
            run.completed_at = datetime.now(timezone.utc)
            await db.commit()

    monkeypatch.setattr(crawler, "_fetch_url", fake_fetch)
    monkeypatch.setattr(crawl_job_service, "run_agent_graph", fake_agent_graph)

    with TestClient(app) as client:
        owner = _register(client, f"agent-crawl-{suffix}@example.com", "Agent Crawl")
        site_id = _create_site(client, owner, domain)

        started = client.post(
            "/agent/run",
            headers=_headers(owner),
            json={"site_id": site_id},
        )
        assert started.status_code == 202, started.text
        run_id = started.json()["run_id"]
        queued_run = client.get(f"/agent/run/{run_id}", headers=_headers(owner))
        crawl_job_id = uuid.UUID(str(queued_run.json()["meta"]["crawl_job_id"]))
        assert client.portal is not None
        client.portal.call(run_crawl_worker_tick, crawl_job_id)

        run = client.get(f"/agent/run/{run_id}", headers=_headers(owner))
        assert run.status_code == 200, run.text
        payload = run.json()
        assert payload["status"] == "completed"
        assert payload["pages_analyzed"] == 1
        assert "No pages found" not in (payload["summary"] or "")

        pages = client.get(f"/sites/{site_id}/pages", headers=_headers(owner))
        assert pages.status_code == 200
        assert pages.json()["total"] == 1

        repeated = client.post(
            "/agent/run",
            headers=_headers(owner),
            json={"site_id": site_id},
        )
        assert repeated.status_code == 202, repeated.text
        repeated_run = client.get(
            f"/agent/run/{repeated.json()['run_id']}",
            headers=_headers(owner),
        )
        repeated_job_id = uuid.UUID(str(repeated_run.json()["meta"]["crawl_job_id"]))
        assert repeated_job_id != crawl_job_id
        client.portal.call(run_crawl_worker_tick, repeated_job_id)
        repeated_done = client.get(
            f"/agent/run/{repeated.json()['run_id']}",
            headers=_headers(owner),
        )
        assert repeated_done.json()["status"] == "completed"


def test_agent_fails_with_crawl_error_instead_of_zero_page_completion(monkeypatch) -> None:
    suffix = uuid.uuid4().hex
    domain = f"agent-crawl-failure-{suffix}.example.com"

    async def failed_fetch(client, url: str, **kwargs):
        del client, url, kwargs
        raise CrawlError("Connection refused by the website")

    monkeypatch.setattr(crawler, "_fetch_url", failed_fetch)

    with TestClient(app) as client:
        owner = _register(client, f"agent-crawl-failure-{suffix}@example.com", "Agent Crawl Failure")
        site_id = _create_site(client, owner, domain)

        started = client.post(
            "/agent/run",
            headers=_headers(owner),
            json={"site_id": site_id},
        )
        assert started.status_code == 202, started.text

        async def exhaust_retry_budget() -> uuid.UUID:
            async with async_session_factory() as db:
                run = await db.get(AgentRun, uuid.UUID(started.json()["run_id"]))
                assert run is not None
                job_id = uuid.UUID(str((run.meta or {})["crawl_job_id"]))
                job = await db.get(JobQueue, job_id)
                assert job is not None
                job.max_attempts = 1
                await db.commit()
                return job_id

        assert client.portal is not None
        crawl_job_id = client.portal.call(exhaust_retry_budget)
        client.portal.call(run_crawl_worker_tick, crawl_job_id)

        run = client.get(
            f"/agent/run/{started.json()['run_id']}",
            headers=_headers(owner),
        )
        assert run.status_code == 200
        payload = run.json()
        assert payload["status"] == "failed"
        assert payload["pages_analyzed"] == 0
        assert "Homepage could not be fetched" in (payload["error"] or "")
