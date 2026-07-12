from fastapi.testclient import TestClient

from app.main import app


def _register(client: TestClient, email: str, workspace_name: str) -> dict:
    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "correct-horse-battery-staple",
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


def test_sites_are_isolated_between_workspaces() -> None:
    with TestClient(app) as client:
        owner_a = _register(client, "tenant-a@example.com", "Tenant A")
        owner_b = _register(client, "tenant-b@example.com", "Tenant B")

        create_response = client.post(
            "/sites",
            headers=_headers(owner_a),
            json={"domain": "tenant-a-example.com", "name": "Tenant A Site"},
        )
        assert create_response.status_code == 201, create_response.text
        site_id = create_response.json()["id"]

        owner_a_sites = client.get("/sites", headers=_headers(owner_a))
        assert owner_a_sites.status_code == 200
        assert [site["id"] for site in owner_a_sites.json()] == [site_id]

        owner_b_sites = client.get("/sites", headers=_headers(owner_b))
        assert owner_b_sites.status_code == 200
        assert owner_b_sites.json() == []

        cross_workspace_read = client.get(f"/sites/{site_id}", headers=_headers(owner_b))
        assert cross_workspace_read.status_code == 404

        unauthenticated = client.get("/sites")
        assert unauthenticated.status_code == 401
