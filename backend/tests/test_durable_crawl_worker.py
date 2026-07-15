from datetime import datetime, timedelta, timezone
import hashlib
import uuid
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import async_session_factory
from app.main import app
from app.models.job_queue import CrawlAttempt, CrawlFrontier, JobQueue
from app.models.site import Site
from app.services import first_party_crawler as crawler
from app.services.crawl_job_service import recover_expired_crawl_leases, run_crawl_worker_tick
from app.services.first_party_crawler import FetchResult


PASSWORD = "correct-horse-battery-staple"


def _register(client: TestClient, suffix: str) -> dict:
    response = client.post(
        "/auth/register",
        json={
            "email": f"durable-crawl-{suffix}@example.com",
            "password": PASSWORD,
            "name": "Durable Crawl",
            "workspace_name": f"Durable Crawl {suffix}",
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
        json={"domain": domain, "name": "Durable Crawl Site"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _result(url: str, body: str, content_type: str = "text/html") -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        status_code=200,
        headers={"content-type": content_type},
        body=body.encode(),
        response_time_ms=10,
        redirect_chain=[],
        truncated=False,
    )


def test_cancelled_crawl_resumes_same_job_and_finishes_from_durable_frontier(monkeypatch) -> None:
    suffix = uuid.uuid4().hex
    domain = f"durable-{suffix}.example.com"

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
                "<html><head><title>Durable home</title></head>"
                "<body><h1>Home</h1><a href='/about'>About</a></body></html>",
            )
        if path == "/about":
            return _result(url, "<html><head><title>About</title></head><body><h1>About</h1></body></html>")
        raise AssertionError(f"Unexpected URL {url}")

    monkeypatch.setattr(crawler, "_fetch_url", fake_fetch)

    with TestClient(app) as client:
        auth = _register(client, suffix)
        headers = _headers(auth)
        site_id = _create_site(client, auth, domain)

        started = client.post(
            "/crawl/site",
            headers=headers,
            json={"site_id": site_id, "max_pages": 10},
        )
        assert started.status_code == 202, started.text
        job_id = started.json()["job_id"]

        cancelled = client.post(f"/crawl/{job_id}/cancel", headers=headers)
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"
        assert cancelled.json()["cancellation_requested"] is True

        resumed = client.post(f"/crawl/{job_id}/resume", headers=headers)
        assert resumed.status_code == 202, resumed.text
        assert resumed.json()["job_id"] == job_id
        assert resumed.json()["status"] == "queued"
        assert resumed.json()["cancellation_requested"] is False

        assert client.portal is not None
        client.portal.call(run_crawl_worker_tick, uuid.UUID(job_id))

        completed = client.get(f"/crawl/{job_id}", headers=headers)
        assert completed.status_code == 200, completed.text
        payload = completed.json()
        assert payload["status"] == "completed"
        assert payload["attempt_count"] == 1
        assert payload["pages_crawled"] == 2
        assert payload["details"]["frontier"]["completed"] == 2

        invalid_resume = client.post(f"/crawl/{job_id}/resume", headers=headers)
        assert invalid_resume.status_code == 409


def test_expired_lease_requeues_fetching_frontier_and_closes_attempt() -> None:
    suffix = uuid.uuid4().hex
    domain = f"lease-{suffix}.example.com"

    with TestClient(app) as client:
        auth = _register(client, suffix)
        site_id = _create_site(client, auth, domain)
        started = client.post(
            "/crawl/site",
            headers=_headers(auth),
            json={"site_id": site_id, "max_pages": 5},
        )
        assert started.status_code == 202, started.text
        job_id = uuid.UUID(started.json()["job_id"])

        async def expire_and_recover() -> tuple[str, str, str | None, str]:
            async with async_session_factory() as db:
                job = await db.get(JobQueue, job_id)
                assert job is not None
                job.status = "running"
                job.attempt_count = 1
                job.lease_owner = "dead-worker"
                job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                db.add(
                    CrawlAttempt(
                        job_id=job.id,
                        attempt_number=1,
                        worker_id="dead-worker",
                        status="running",
                    )
                )
                url = f"https://{domain}/"
                db.add(
                    CrawlFrontier(
                        job_id=job.id,
                        url=url,
                        url_hash=hashlib.sha256(url.encode()).hexdigest(),
                        status="fetching",
                        attempt_count=1,
                    )
                )
                await db.commit()

            async with async_session_factory() as db:
                recovered = await recover_expired_crawl_leases(db)
                assert recovered == 1
                job = await db.get(JobQueue, job_id)
                attempt = await db.scalar(
                    select(CrawlAttempt).where(CrawlAttempt.job_id == job_id)
                )
                frontier = await db.scalar(
                    select(CrawlFrontier).where(CrawlFrontier.job_id == job_id)
                )
                site = await db.get(Site, job.site_id) if job else None
                assert job is not None and attempt is not None and frontier is not None and site is not None
                return job.status, frontier.status, attempt.error_code, site.status

        assert client.portal is not None
        job_status, frontier_status, attempt_error, site_status = client.portal.call(expire_and_recover)
        assert job_status == "retry_wait"
        assert frontier_status == "queued"
        assert attempt_error == "lease_expired"
        assert site_status == "crawl_queued"
