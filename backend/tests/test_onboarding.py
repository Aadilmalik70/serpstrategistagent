import uuid

from fastapi.testclient import TestClient

from app.main import app


PASSWORD = "correct-horse-battery-staple"


def _register(client: TestClient, email: str) -> dict:
    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "Onboarding Owner",
            "workspace_name": "Onboarding Workspace",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _headers(auth: dict) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {auth['access_token']}",
        "X-Workspace-ID": auth["workspace"]["id"],
    }


def test_onboarding_persists_materializes_site_and_resumes() -> None:
    suffix = uuid.uuid4().hex
    domain = f"onboarding-{suffix}.example.com"

    with TestClient(app) as client:
        auth = _register(client, f"onboarding-{suffix}@example.com")
        headers = _headers(auth)

        initial = client.get("/onboarding", headers=headers)
        assert initial.status_code == 200, initial.text
        assert initial.json()["current_step"] == "profile"
        assert initial.json()["completion_percent"] == 0

        profile = client.put(
            "/onboarding/step",
            headers=headers,
            json={
                "step": "profile",
                "answers": {
                    "full_name": "Aadil Khan",
                    "company_name": "SERP Strategists",
                    "role": "founder",
                    "business_type": "saas",
                    "country": "IN",
                    "timezone": "Asia/Kolkata",
                },
                "complete_step": True,
                "next_step": "site",
            },
        )
        assert profile.status_code == 200, profile.text
        assert profile.json()["current_step"] == "site"
        assert profile.json()["answers"]["profile"]["company_name"] == "SERP Strategists"

        resumed = client.get("/onboarding", headers=headers)
        assert resumed.status_code == 200
        assert resumed.json()["current_step"] == "site"
        assert "profile" in resumed.json()["completed_steps"]

        invalid_site = client.put(
            "/onboarding/step",
            headers=headers,
            json={
                "step": "site",
                "answers": {"website_url": "not-a-domain", "site_name": "Invalid"},
                "complete_step": True,
                "next_step": "cms",
            },
        )
        assert invalid_site.status_code == 400
        assert "valid website URL" in invalid_site.json()["detail"]

        site = client.put(
            "/onboarding/step",
            headers=headers,
            json={
                "step": "site",
                "answers": {
                    "website_url": f"https://{domain}/some-path",
                    "site_name": "SERP Strategists",
                    "primary_market": "US",
                    "language": "English",
                },
                "complete_step": True,
                "next_step": "cms",
            },
        )
        assert site.status_code == 200, site.text
        site_answers = site.json()["answers"]["site"]
        assert site_answers["domain"] == domain
        assert site_answers["website_url"] == f"https://{domain}"
        assert site_answers["site_id"]

        sites = client.get("/sites", headers=headers)
        assert sites.status_code == 200, sites.text
        assert len(sites.json()) == 1
        assert sites.json()[0]["id"] == site_answers["site_id"]
        assert sites.json()[0]["domain"] == domain

        premature = client.post(
            "/onboarding/complete",
            headers=headers,
            json={"launch_operator": False},
        )
        assert premature.status_code == 409

        skipped_cms = client.put(
            "/onboarding/step",
            headers=headers,
            json={
                "step": "cms",
                "answers": {"cms": "skipped", "skipped": True},
                "complete_step": True,
                "next_step": "google",
            },
        )
        assert skipped_cms.status_code == 200, skipped_cms.text

        skipped_google = client.put(
            "/onboarding/step",
            headers=headers,
            json={
                "step": "google",
                "answers": {"skipped": True},
                "complete_step": True,
                "next_step": "goals",
            },
        )
        assert skipped_google.status_code == 200, skipped_google.text

        goals = client.put(
            "/onboarding/step",
            headers=headers,
            json={
                "step": "goals",
                "answers": {"priorities": ["Fix technical SEO", "Grow AI-search visibility"]},
                "complete_step": True,
                "next_step": "review",
            },
        )
        assert goals.status_code == 200, goals.text

        completed = client.post(
            "/onboarding/complete",
            headers=headers,
            json={"launch_operator": False},
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "completed"
        assert completed.json()["completed_at"] is not None
        assert completed.json()["answers"]["launch"]["site_id"] == site_answers["site_id"]


def test_onboarding_reuses_the_same_site_on_edit() -> None:
    suffix = uuid.uuid4().hex
    domain = f"onboarding-edit-{suffix}.example.com"

    with TestClient(app) as client:
        auth = _register(client, f"onboarding-edit-{suffix}@example.com")
        headers = _headers(auth)

        first = client.put(
            "/onboarding/step",
            headers=headers,
            json={
                "step": "site",
                "answers": {"website_url": domain, "site_name": "First name"},
                "complete_step": True,
            },
        )
        assert first.status_code == 200, first.text
        first_id = first.json()["answers"]["site"]["site_id"]

        second = client.put(
            "/onboarding/step",
            headers=headers,
            json={
                "step": "site",
                "answers": {"website_url": domain, "site_name": "Updated name"},
                "complete_step": True,
            },
        )
        assert second.status_code == 200, second.text
        assert second.json()["answers"]["site"]["site_id"] == first_id

        sites = client.get("/sites", headers=headers)
        assert sites.status_code == 200
        assert len(sites.json()) == 1
        assert sites.json()[0]["name"] == "Updated name"


def test_onboarding_is_workspace_scoped() -> None:
    with TestClient(app) as client:
        first = _register(client, f"onboarding-first-{uuid.uuid4().hex}@example.com")
        second = _register(client, f"onboarding-second-{uuid.uuid4().hex}@example.com")

        saved = client.put(
            "/onboarding/step",
            headers=_headers(first),
            json={
                "step": "profile",
                "answers": {
                    "full_name": "First Owner",
                    "company_name": "First Workspace",
                    "role": "founder",
                    "business_type": "saas",
                    "country": "IN",
                    "timezone": "Asia/Kolkata",
                },
                "complete_step": True,
            },
        )
        assert saved.status_code == 200

        isolated = client.get("/onboarding", headers=_headers(second))
        assert isolated.status_code == 200
        assert isolated.json()["answers"] == {}
        assert isolated.json()["completed_steps"] == []
