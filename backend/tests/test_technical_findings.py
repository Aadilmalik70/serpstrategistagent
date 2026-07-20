import uuid
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from app.main import app
from app.services import first_party_crawler as crawler
from app.services.crawl_job_service import run_crawl_worker_tick
from app.services.first_party_crawler import FetchResult
from app.services.github_patch_planner import RepositoryPatchPlan


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
        assert client.portal is not None
        client.portal.call(run_crawl_worker_tick, uuid.UUID(crawl.json()["job_id"]))

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
        client.portal.call(run_crawl_worker_tick, uuid.UUID(recrawl.json()["job_id"]))
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
        client.portal.call(
            run_crawl_worker_tick,
            uuid.UUID(regression_crawl.json()["job_id"]),
        )
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


def test_exact_github_patch_supersedes_active_simulation_action(monkeypatch) -> None:
    suffix = uuid.uuid4().hex
    domain = f"patch-ready-{suffix}.example.com"
    planning = {"ready": False, "reason": "No exact source file was available yet."}

    async def fake_fetch(client, url: str, **kwargs):
        del client, kwargs
        path = urlsplit(url).path
        if path == "/robots.txt":
            return _result(url, "User-agent: *\nSitemap: /sitemap.xml\n", "text/plain")
        if path == "/sitemap.xml":
            return _result(url, "<urlset></urlset>", "application/xml")
        if path == "/":
            useful = "useful original product information " * 55
            return _result(
                url,
                "<html><head><title>Evidence-led organic search growth operator</title>"
                "<meta name='description' content='A complete description of a governed organic search growth operator for technical teams.'>"
                "<meta name='viewport' content='width=device-width'>"
                "<link rel='canonical' href='/'>"
                "<script type='application/ld+json'>{}</script></head>"
                f"<body><h1>Organic search growth operator</h1><img src='/hero.png'><p>{useful}</p></body></html>",
            )
        raise AssertionError(f"Unexpected URL {url}")

    async def fake_plan(_db, *, finding, **_kwargs):
        if finding.finding_type != "images_missing_alt" or not planning["ready"]:
            return RepositoryPatchPlan.fallback(
                "source_file_not_resolved",
                planning["reason"],
            )
        return RepositoryPatchPlan(
            status="ready",
            reason_code="exact_patch_ready",
            reason="Exact patch ready.",
            execution_target={
                "adapter": "github",
                "base_branch": "main",
                "repository": "operator/site",
                "source_path": "frontend/app/page.tsx",
                "planner": "repository-ai-v1",
            },
            proposed_diff={
                "summary": "Add contextual hero image alt text",
                "affected_pages": 1,
                "affected_urls": ["/"],
                "mode": "exact_github_patch",
                "commit_message": "Fix homepage image alternative text",
                "planner": {
                    "status": "ready",
                    "version": "repository-ai-v1",
                    "source_path": "frontend/app/page.tsx",
                    "expected_sha": "b" * 40,
                    "changed_lines": 2,
                    "model": "test-model",
                },
                "files": [
                    {
                        "path": "frontend/app/page.tsx",
                        "operation": "update",
                        "content": '<Image src="/hero.png" alt="AI growth operator dashboard" />\n',
                        "expected_sha": "b" * 40,
                    }
                ],
            },
            rollback_plan={
                "strategy": "close_draft_pr_and_delete_unchanged_branch",
                "required": True,
            },
        )

    monkeypatch.setattr(crawler, "_fetch_url", fake_fetch)
    monkeypatch.setattr(
        "app.services.github_patch_planner.plan_patch_for_finding",
        fake_plan,
    )

    with TestClient(app) as client:
        owner = _register(client, f"patch-owner-{suffix}@example.com", "Patch Owner")
        headers = _headers(owner)
        site = client.post(
            "/sites",
            headers=headers,
            json={"domain": domain, "name": "Patch Test Site"},
        )
        assert site.status_code == 201, site.text
        site_id = site.json()["id"]

        crawl = client.post(
            "/crawl/site",
            headers=headers,
            json={"site_id": site_id, "max_pages": 5},
        )
        assert crawl.status_code == 202, crawl.text
        assert client.portal is not None
        client.portal.call(run_crawl_worker_tick, uuid.UUID(crawl.json()["job_id"]))

        first = client.post(
            f"/technical-findings/sites/{site_id}/refresh",
            headers=headers,
        )
        assert first.status_code == 200, first.text
        findings = client.get(
            f"/technical-findings/sites/{site_id}?status=active",
            headers=headers,
        ).json()["items"]
        image_finding = next(item for item in findings if item["finding_type"] == "images_missing_alt")
        simulation_action_id = image_finding["action_id"]
        assert image_finding["action_adapter"] == "simulation"
        assert image_finding["patch_status"] == "fallback"

        planning["reason"] = "The affected URL still maps to multiple source files."
        fallback_refresh = client.post(
            f"/technical-findings/sites/{site_id}/refresh",
            headers=headers,
        )
        assert fallback_refresh.status_code == 200, fallback_refresh.text
        fallback_items = client.get(
            f"/technical-findings/sites/{site_id}?status=active",
            headers=headers,
        ).json()["items"]
        refreshed_fallback = next(
            item for item in fallback_items if item["finding_type"] == "images_missing_alt"
        )
        assert refreshed_fallback["action_id"] == simulation_action_id
        assert refreshed_fallback["patch_reason"] == planning["reason"]
        simulation_detail = client.get(
            f"/operator-actions/{simulation_action_id}",
            headers=headers,
        )
        assert simulation_detail.status_code == 200, simulation_detail.text
        assert any(
            event["event_type"] == "action_plan_refreshed"
            for event in simulation_detail.json()["events"]
        )

        planning["ready"] = True
        refreshed = client.post(
            f"/technical-findings/sites/{site_id}/refresh",
            headers=headers,
        )
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["actions_created"] >= 1

        upgraded_findings = client.get(
            f"/technical-findings/sites/{site_id}?status=active",
            headers=headers,
        ).json()["items"]
        upgraded = next(item for item in upgraded_findings if item["finding_type"] == "images_missing_alt")
        assert upgraded["action_id"] != simulation_action_id
        assert upgraded["action_adapter"] == "github"
        assert upgraded["patch_status"] == "ready"
        assert upgraded["patch_source_path"] == "frontend/app/page.tsx"

        github_action = client.get(
            f"/operator-actions/{upgraded['action_id']}",
            headers=headers,
        )
        assert github_action.status_code == 200, github_action.text
        assert github_action.json()["status"] == "needs_approval"
        assert github_action.json()["approval_policy"]["mode"] == "manual_approval"
        assert github_action.json()["proposed_diff"]["files"][0]["expected_sha"] == "b" * 40

        superseded = client.get(
            f"/operator-actions/{simulation_action_id}",
            headers=headers,
        )
        assert superseded.status_code == 200, superseded.text
        assert superseded.json()["status"] == "cancelled"


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
