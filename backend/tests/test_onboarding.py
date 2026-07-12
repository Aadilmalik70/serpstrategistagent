import uuid

from fastapi.testclient import TestClient

from app.main import app


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


def test_onboarding_persists_and_resumes_by_workspace() -> None:
    suffix = uuid.uuid4().hex
    with TestClient(app) as client:
        owner = _register(client, f"onboarding-owner-{suffix}@example.com", "Owner Workspace")
        outsider = _register(client, f"onboarding-outsider-{suffix}@example.com", "Outsider Workspace")

        initial = client.get("/onboarding", headers=_headers(owner))
        assert initial.status_code == 200, initial.text
        assert initial.json()["current_step"] == "profile"
        assert initial.json()["completed_steps"] == []

        saved = client.put(
            "/onboarding/step",
            headers=_headers(owner),
            json={
                "step": "profile",
                "data": {
                    "full_name": "Onboarding Owner",
                    "company_name": "SERP Test",
                    "role": "founder",
                    "business_type": "saas",
                    "country": "IN",
                    "timezone": "Asia/Kolkata",
                },
                "next_step": "site",
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["current_step"] == "site"
        assert saved.json()["completed_steps"] == ["profile"]

        resumed = client.get("/onboarding", headers=_headers(owner))
        assert resumed.status_code == 200
        assert resumed.json()["data"]["profile"]["company_name"] == "SERP Test"

        outsider_state = client.get("/onboarding", headers=_headers(outsider))
        assert outsider_state.status_code == 200
        assert outsider_state.json()["data"] == {}
        assert outsider_state.json()["completed_steps"] == []


def test_onboarding_requires_minimum_steps_before_completion() -> None:
    suffix = uuid.uuid4().hex
    with TestClient(app) as client:
        owner = _register(client, f"onboarding-minimum-{suffix}@example.com", "Minimum Workspace")
        headers = _headers(owner)

        client.get("/onboarding", headers=headers)
        incomplete = client.post(
            "/onboarding/complete",
            headers=headers,
            json={"launch_operator": True},
        )
        assert incomplete.status_code == 409

        steps = [
            ("profile", {"company_name": "Minimum Co"}, "site"),
            ("site", {"url": f"https://minimum-{suffix}.example.com"}, "cms"),
            ("goals", {"priorities": ["technical_seo"]}, "review"),
        ]
        for step, data, next_step in steps:
            response = client.put(
                "/onboarding/step",
                headers=headers,
                json={"step": step, "data": data, "next_step": next_step},
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

        cannot_modify = client.put(
            "/onboarding/step",
            headers=headers,
            json={"step": "profile", "data": {"company_name": "Changed"}},
        )
        assert cannot_modify.status_code == 409
