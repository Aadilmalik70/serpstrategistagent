import uuid
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from app.main import app
from app.services import first_party_crawler as crawler
from app.services.first_party_crawler import FetchResult


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


def _result(url: str, body: str, content_type: str = "text/html") -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        status_code=200,
        headers={"content-type": content_type},
        body=body.encode("utf-8"),
        response_time_ms=15,
        redirect_chain=[],
        truncated=False,
    )


def test_findings_are_reconciled_and_regressions_create_new_governed_actions(monkeypatch) -> None:
    suffix = uuid.uuid4().hex
    domain = f"findings-{suffix}.example.com"
    state = {"fixed": False}

    async def fake_fetch(client, url: str, **kwargs):
        del client, kwargs
        path = urlsplit(url).path
        if path == "/robots.txt":
            return _result(url, "User-agent: *\nSitemap: /sitemap.xml\n", "text/plain")
        if path == "/sitemap.xml":
            return _result(url, "<urlset></urlset>", "application/xml")
        if not state["fixed"]:
            if path == "/":
                return _result(
                    url,
                    "<html><head><title>Shared technical SEO page title</title></head>"
                    "<body><h1>Home</h1><a href='/about'>About</a><p>Short.</p></body></html>",
                )
            if path == "/about":
                return _result(
                    url,
                    "<html><head><title>Shared technical SEO page title</title></head>"
                    "<body><h1>About</h1><p>Short.</p></body></html>",
                )
        useful = "useful evidence and original information " * 45
        if path == "/":
            return _result(
                url,
                "<html><head><title>Evidence-led SEO operations platform</title>"
                "<meta name='description' content='A complete description of the evidence-led SEO operations platform.'>"
                "<meta name='viewport' content='width=device-width'>"
                "<link rel='canonical' href='/'>"
                "<script type='application/ld+json'>{}</script></head>"
                f"<body><h1>SEO operations platform</h1><a href='/about'>About</a><p>{useful}</p></body></html>",
            )
        if path == "/about":
            return _result(
                url,
                "<html><head><title>About our technical search team</title>"
                "<meta name='description' content='Learn how our technical search team builds measurable organic growth systems.'>"
                "<meta name='viewport' content='width=device-width'>"
                "<link rel='canonical' href='/about'></head>"
                f"<body><h1>About the technical search team</h1><p>{useful}</p></body></html>",
            )
        raise AssertionError(f"Unexpected URL {url}")

    monkeypatch.setattr(crawler, "_fetch_url", fake_fetch)

    with TestClient(app) as client:
        owner = _register(client, f"finding-owner-{suffix}@example.com", "Finding Owner")
        outsider = _register(client, f"finding-outsider-{suffix}@example.com", "Finding Outsider")
        site = client.post(
            "/sites",
            headers=_headers(owner),
            json={"domain": domain, "name": "Finding Test Site"},
        )
        assert site.status_code == 201, site.text
        site_id = site.json()["id"]

        crawl = client.post(
            "/crawl/site",
            headers=_headers(owner),
            json={"site_id": site_id, "max_pages": 10},
        )
        assert crawl.status_code == 202, crawl.text

        first = client.post(
            f"/technical-findings/sites/{site_id}/refresh",
            headers=_headers(owner),
        )
        assert first.status_code == 200, first.text
        first_result = first.json()
        assert first_result["created"] > 0
        assert first_result["actions_created"] > 0

        queue = client.get(
            f"/technical-findings/sites/{site_id}?status=active",
            headers=_headers(owner),
        )
        assert queue.status_code == 200, queue.text
        items = queue.json()["items"]
        assert len({item["fingerprint"] for item in items}) == len(items)
        duplicate = next(item for item in items if item["finding_type"] == "duplicate_title")
        assert len(duplicate["affected_urls"]) == 2
        assert duplicate["action_id"]
        assert duplicate["action_status"] in {"approved", "needs_approval", "blocked"}

        repeated = client.post(
            f"/technical-findings/sites/{site_id}/refresh",
            headers=_headers(owner),
        )
        assert repeated.status_code == 200
        assert repeated.json()["created"] == 0
        assert repeated.json()["actions_created"] == 0

        state["fixed"] = True
        recrawl = client.post(
            "/crawl/site",
            headers=_headers(owner),
            json={"site_id": site_id, "max_pages": 10},
        )
        assert recrawl.status_code == 202
        resolved = client.post(
            f"/technical-findings/sites/{site_id}/refresh",
            headers=_headers(owner),
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["resolved"] > 0

        state["fixed"] = False
        regression_crawl = client.post(
            "/crawl/site",
            headers=_headers(owner),
            json={"site_id": site_id, "max_pages": 10},
        )
        assert regression_crawl.status_code == 202
        regressed = client.post(
            f"/technical-findings/sites/{site_id}/refresh",
            headers=_headers(owner),
        )
        assert regressed.status_code == 200, regressed.text
        assert regressed.json()["regressed"] > 0
        assert regressed.json()["actions_created"] > 0

        outsider_read = client.get(
            f"/technical-findings/sites/{site_id}",
            headers=_headers(outsider),
        )
        assert outsider_read.status_code == 404


def test_legacy_rejection_keeps_cors_headers() -> None:
    with TestClient(app) as client:
        response = client.options(
            f"/actions/fix-plan-bulk/{uuid.uuid4()}",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"

        rejected = client.post(
            f"/actions/fix-plan-bulk/{uuid.uuid4()}",
            headers={"Origin": "http://localhost:3000"},
            json={},
        )
        assert rejected.status_code == 410
        assert rejected.headers["access-control-allow-origin"] == "http://localhost:3000"
