import uuid
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from app.main import app
from app.database import async_session_factory
from app.models.job_queue import JobQueue
from app.services.crawl_job_service import run_crawl_worker_tick
from app.services import first_party_crawler as crawler
from app.services.first_party_crawler import CrawlError, FetchResult, PageHtmlParser


PASSWORD = "correct-horse-battery-staple"


def test_validated_destination_is_pinned_without_changing_host_identity() -> None:
    pinned, sni_hostname, host_header = crawler._pinned_target_url(
        "https://example.com/path?q=1",
        "203.0.113.10",
    )
    assert pinned == "https://203.0.113.10/path?q=1"
    assert sni_hostname == "example.com"
    assert host_header == "example.com"


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
        json={"domain": domain, "name": "Crawler Test"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _result(url: str, body: str, *, status: int = 200, content_type: str = "text/html") -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        status_code=status,
        headers={"content-type": content_type},
        body=body.encode("utf-8"),
        response_time_ms=12,
        redirect_chain=[],
        truncated=False,
    )


def test_html_parser_extracts_visible_metadata() -> None:
    parser = PageHtmlParser()
    parser.feed(
        """
        <html lang="en"><head>
          <title>Example Growth Page</title>
          <meta name="description" content="A useful description">
          <meta property="og:title" content="OG title">
          <link rel="canonical" href="https://example.com/growth">
          <script type="application/ld+json">{"@type":"WebPage"}</script>
        </head><body>
          <h1>Grow organic traffic</h1><h2>Evidence</h2>
          <p>Visible words should be counted.</p>
          <a href="/about">About</a><img src="hero.png" alt="">
        </body></html>
        """
    )
    assert parser.title == "Example Growth Page"
    assert parser.meta["description"] == "A useful description"
    assert parser.headings("h1") == ["Grow organic traffic"]
    assert parser.canonical == "https://example.com/growth"
    assert parser.links == ["/about"]
    assert parser.json_ld_count == 1
    assert parser.word_count >= 5


def test_first_party_crawl_discovers_pages_and_persists_progress(monkeypatch) -> None:
    suffix = uuid.uuid4().hex
    domain = f"crawler-{suffix}.example.com"

    async def fake_fetch(client, url: str, **kwargs):
        del client, kwargs
        path = urlsplit(url).path
        if path == "/robots.txt":
            return _result(
                url,
                "User-agent: *\nDisallow: /private\n",
                content_type="text/plain",
            )
        if path == "/sitemap.xml":
            return _result(url, "<urlset></urlset>", content_type="application/xml")
        if path == "/":
            return _result(
                url,
                """
                <html lang="en"><head>
                  <title>SERP Test Home</title>
                  <meta name="description" content="A complete homepage description for crawler tests.">
                  <meta name="viewport" content="width=device-width">
                  <link rel="canonical" href="/">
                </head><body>
                  <h1>Home</h1>
                  <a href="/about?utm_source=test">About</a>
                  <a href="/private">Private</a>
                  <a href="https://external.example.org/page">External</a>
                </body></html>
                """,
            )
        if path == "/about":
            return _result(
                url,
                "<html><head><title>About us</title></head><body><h1>About</h1><a href='/pricing'>Pricing</a></body></html>",
            )
        if path == "/pricing":
            return _result(
                url,
                "<html><head><title>Pricing</title></head><body><h1>Pricing</h1><p>Simple plans for growth teams.</p></body></html>",
            )
        raise AssertionError(f"Unexpected crawler URL: {url}")

    monkeypatch.setattr(crawler, "_fetch_url", fake_fetch)

    with TestClient(app) as client:
        owner = _register(client, f"crawler-owner-{suffix}@example.com", "Crawler Owner")
        outsider = _register(client, f"crawler-outsider-{suffix}@example.com", "Crawler Outsider")
        site_id = _create_site(client, owner, domain)

        started = client.post(
            "/crawl/site",
            headers=_headers(owner),
            json={"site_id": site_id, "max_pages": 10},
        )
        assert started.status_code == 202, started.text
        job_id = started.json()["job_id"]
        assert started.json()["status"] == "queued"
        assert client.portal is not None
        client.portal.call(run_crawl_worker_tick, uuid.UUID(job_id))

        status = client.get(f"/crawl/{job_id}", headers=_headers(owner))
        assert status.status_code == 200, status.text
        payload = status.json()
        assert payload["status"] == "completed"
        assert payload["adapter"] == "first_party"
        assert payload["pages_crawled"] == 3
        assert payload["pages_discovered"] >= 4
        assert payload["details"]["robots"]["blocked_urls"] == 1

        pages = client.get(f"/sites/{site_id}/pages?limit=100", headers=_headers(owner))
        assert pages.status_code == 200, pages.text
        assert pages.json()["total"] == 3
        paths = {item["path"] for item in pages.json()["items"]}
        assert paths == {"/", "/about", "/pricing"}
        homepage = next(item for item in pages.json()["items"] if item["path"] == "/")
        assert homepage["title"] == "SERP Test Home"
        assert homepage["canonical_url"].endswith("/")
        assert homepage["meta"]["internal_links_count"] == 2
        assert homepage["meta"]["external_links_count"] == 1

        latest = client.get(f"/crawl/site/{site_id}/latest", headers=_headers(owner))
        assert latest.status_code == 200
        assert latest.json()["job_id"] == job_id

        outsider_read = client.get(f"/crawl/{job_id}", headers=_headers(outsider))
        assert outsider_read.status_code == 404


def test_first_party_crawl_exposes_terminal_failure(monkeypatch) -> None:
    suffix = uuid.uuid4().hex
    domain = f"crawler-failure-{suffix}.example.com"

    async def failed_fetch(client, url: str, **kwargs):
        del client, url, kwargs
        raise CrawlError("Connection refused by the website")

    monkeypatch.setattr(crawler, "_fetch_url", failed_fetch)

    with TestClient(app) as client:
        owner = _register(client, f"crawler-failure-{suffix}@example.com", "Crawler Failure")
        site_id = _create_site(client, owner, domain)
        started = client.post(
            "/crawl/site",
            headers=_headers(owner),
            json={"site_id": site_id, "max_pages": 5},
        )
        assert started.status_code == 202, started.text
        job_id = uuid.UUID(started.json()["job_id"])

        async def exhaust_retry_budget() -> None:
            async with async_session_factory() as db:
                job = await db.get(JobQueue, job_id)
                assert job is not None
                job.max_attempts = 1
                await db.commit()

        assert client.portal is not None
        client.portal.call(exhaust_retry_budget)
        client.portal.call(run_crawl_worker_tick, job_id)

        status = client.get(
            f"/crawl/{job_id}",
            headers=_headers(owner),
        )
        assert status.status_code == 200
        payload = status.json()
        assert payload["status"] == "failed"
        assert payload["pages_crawled"] == 0
        assert "Homepage could not be fetched" in (payload["error"] or "")

        site = client.get(f"/sites/{site_id}", headers=_headers(owner))
        assert site.status_code == 200
        assert site.json()["status"] == "crawl_failed"
        assert site.json()["health_score"] is None
