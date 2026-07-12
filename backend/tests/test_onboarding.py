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


def test_onboarding_persists_and_resumes() -> None:
    with TestClient(app) as client:
        auth = _register(client, f"onboarding-{uuid.uuid4().hex}@example.com")
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

        premature = client.post(
            "/onboarding/complete",
            headers=headers,
            json={"launch_operator": True},
        )
        assert premature.status_code == 409

        for step, answers, next_step in [
            ("site", {"website_url": "https://serpstrategists.com", "site_name": "SERP Strategists"}, "cms"),
            ("goals", {"priorities": ["technical_seo", "ai_visibility"]}, "review"),
        ]:
            response = client.put(
                "/onboarding/step",
                headers=headers,
                json={
                    "step": step,
                    "answers": answers,
                    "complete_step": True,
                    "next_step": next_step,
                },
            )
            assert response.status_code == 200, response.text

        completed = client.post(
            "/onboarding/complete",
            headers=headers,
            json={"launch_operator": True},
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "completed"
        assert completed.json()["completed_at"] is not None


def test_onboarding_is_workspace_scoped() -> None:
    with TestClient(app) as client:
        first = _register(client, f"onboarding-first-{uuid.uuid4().hex}@example.com")
        second = _register(client, f"onboarding-second-{uuid.uuid4().hex}@example.com")

        saved = client.put(
            "/onboarding/step",
            headers=_headers(first),
            json={
                "step": "profile",
                "answers": {"company_name": "First Workspace"},
                "complete_step": True,
            },
        )
        assert saved.status_code == 200

        isolated = client.get("/onboarding", headers=_headers(second))
        assert isolated.status_code == 200
        assert isolated.json()["answers"] == {}
        assert isolated.json()["completed_steps"] == []
