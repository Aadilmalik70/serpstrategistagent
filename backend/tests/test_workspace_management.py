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


def _auth_headers(auth: dict, workspace_id: str | None = None) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {auth['access_token']}",
        "X-Workspace-ID": workspace_id or auth["workspace"]["id"],
    }


def test_workspace_invitation_and_role_controls() -> None:
    with TestClient(app) as client:
        owner = _register(client, "workspace-owner@example.com", "Owner Workspace")
        invited = _register(client, "workspace-member@example.com", "Member Personal")
        wrong_user = _register(client, "workspace-wrong@example.com", "Wrong Personal")

        owner_headers = _auth_headers(owner)
        invitation_response = client.post(
            "/workspaces/invitations",
            headers=owner_headers,
            json={"email": "workspace-member@example.com", "role": "member"},
        )
        assert invitation_response.status_code == 201, invitation_response.text
        invitation = invitation_response.json()
        assert invitation["accept_token"]

        wrong_accept = client.post(
            "/workspaces/invitations/accept",
            headers=_auth_headers(wrong_user),
            json={"token": invitation["accept_token"]},
        )
        assert wrong_accept.status_code == 403

        accepted = client.post(
            "/workspaces/invitations/accept",
            headers=_auth_headers(invited),
            json={"token": invitation["accept_token"]},
        )
        assert accepted.status_code == 200, accepted.text
        shared_workspace = accepted.json()
        assert shared_workspace["id"] == owner["workspace"]["id"]
        assert shared_workspace["role"] == "member"

        invited_workspaces = client.get(
            "/workspaces",
            headers={"Authorization": f"Bearer {invited['access_token']}"},
        )
        assert invited_workspaces.status_code == 200
        assert {workspace["id"] for workspace in invited_workspaces.json()} == {
            invited["workspace"]["id"],
            owner["workspace"]["id"],
        }

        shared_member_headers = _auth_headers(invited, owner["workspace"]["id"])
        member_create_site = client.post(
            "/sites",
            headers=shared_member_headers,
            json={"domain": "member-cannot-create.example.com", "name": "Denied"},
        )
        assert member_create_site.status_code == 403

        members_response = client.get("/workspaces/members", headers=owner_headers)
        assert members_response.status_code == 200
        members = members_response.json()
        invited_membership = next(
            member for member in members if member["email"] == "workspace-member@example.com"
        )
        owner_membership = next(
            member for member in members if member["email"] == "workspace-owner@example.com"
        )

        promote = client.patch(
            f"/workspaces/members/{invited_membership['id']}",
            headers=owner_headers,
            json={"role": "admin"},
        )
        assert promote.status_code == 200, promote.text
        assert promote.json()["role"] == "admin"

        admin_create_site = client.post(
            "/sites",
            headers=shared_member_headers,
            json={"domain": "admin-can-create.example.com", "name": "Allowed"},
        )
        assert admin_create_site.status_code == 201, admin_create_site.text

        final_owner_demotion = client.patch(
            f"/workspaces/members/{owner_membership['id']}",
            headers=owner_headers,
            json={"role": "member"},
        )
        assert final_owner_demotion.status_code == 409

        final_owner_removal = client.delete(
            f"/workspaces/members/{owner_membership['id']}",
            headers=owner_headers,
        )
        assert final_owner_removal.status_code == 409
