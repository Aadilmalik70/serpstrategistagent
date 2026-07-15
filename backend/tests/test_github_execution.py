import asyncio
import base64
from datetime import datetime, timezone
from urllib.parse import urlparse
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.database import async_session_factory, engine
from app.main import app
from app.models.github_app import GitHubAppInstallation, GitHubExecution, GitHubRepositoryConnection
from app.services import execution_adapters, execution_service
from app.services.github_execution_service import GitHubExecutionAdapter


PASSWORD = "correct-horse-battery-staple"
BASE_SHA = "a" * 40
OLD_BLOB_SHA = "b" * 40
BASE_TREE_SHA = "c" * 40
NEW_BLOB_SHA = "d" * 40
NEW_TREE_SHA = "e" * 40
COMMIT_SHA = "f" * 40


class _Response:
    def __init__(self, status_code: int, payload: object):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


class _GitHubProviderClient:
    def __init__(self) -> None:
        self.branch_sha: str | None = None
        self.pull_request: dict | None = None
        self.commit_message = ""
        self.calls: list[tuple[str, str]] = []

    async def request(self, method: str, url: str, **kwargs) -> _Response:
        path = urlparse(url).path
        self.calls.append((method, path))
        payload = kwargs.get("json") or {}
        params = kwargs.get("params") or {}

        if method == "GET" and path.endswith("/git/ref/heads/main"):
            return _Response(200, {"object": {"sha": BASE_SHA}})
        if method == "GET" and "/git/ref/heads/serp-operator%2Faction-" in path:
            if self.branch_sha is None:
                return _Response(404, {"message": "Not Found"})
            return _Response(200, {"object": {"sha": self.branch_sha}})
        if method == "GET" and path.endswith(f"/git/commits/{BASE_SHA}"):
            return _Response(200, {"sha": BASE_SHA, "tree": {"sha": BASE_TREE_SHA}, "parents": []})
        if method == "GET" and path.endswith(f"/git/commits/{COMMIT_SHA}"):
            return _Response(
                200,
                {
                    "sha": COMMIT_SHA,
                    "tree": {"sha": NEW_TREE_SHA},
                    "parents": [{"sha": BASE_SHA}],
                    "message": self.commit_message,
                },
            )
        if method == "GET" and "/contents/content/page.md" in path:
            ref = params.get("ref")
            content = b"new title\n" if ref != BASE_SHA else b"old title\n"
            object_sha = NEW_BLOB_SHA if ref != BASE_SHA else OLD_BLOB_SHA
            return _Response(
                200,
                {
                    "type": "file",
                    "sha": object_sha,
                    "encoding": "base64",
                    "content": base64.b64encode(content).decode("ascii"),
                },
            )
        if method == "POST" and path.endswith("/git/blobs"):
            return _Response(201, {"sha": NEW_BLOB_SHA})
        if method == "POST" and path.endswith("/git/trees"):
            assert payload["base_tree"] == BASE_TREE_SHA
            return _Response(201, {"sha": NEW_TREE_SHA})
        if method == "POST" and path.endswith("/git/commits"):
            self.commit_message = payload["message"]
            return _Response(201, {"sha": COMMIT_SHA})
        if method == "POST" and path.endswith("/git/refs"):
            self.branch_sha = payload["sha"]
            return _Response(201, {"object": {"sha": self.branch_sha}})
        if method == "GET" and path.endswith("/pulls"):
            return _Response(200, [self.pull_request] if self.pull_request else [])
        if method == "POST" and path.endswith("/pulls"):
            self.pull_request = {
                "number": 17,
                "html_url": "https://github.com/operator/site/pull/17",
                "state": "open",
                "draft": True,
                "merged": False,
                "merged_at": None,
                "head": {"sha": COMMIT_SHA, "ref": payload["head"]},
                "base": {"sha": BASE_SHA, "ref": payload["base"]},
            }
            return _Response(201, self.pull_request)
        if method == "GET" and path.endswith("/pulls/17"):
            return _Response(200, self.pull_request)
        if method == "PATCH" and path.endswith("/pulls/17"):
            assert self.pull_request is not None
            self.pull_request["state"] = "closed"
            return _Response(200, self.pull_request)
        if method == "DELETE" and "/git/refs/heads/serp-operator%2Faction-" in path:
            self.branch_sha = None
            return _Response(204, {})
        raise AssertionError(f"Unexpected GitHub request: {method} {path} {kwargs}")


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


async def _reset_database_pool_for_test_loop() -> None:
    await engine.dispose(close=False)


async def _authorize_repository(
    workspace_id: str,
    site_id: str,
) -> None:
    async with async_session_factory() as db:
        installation = GitHubAppInstallation(
            workspace_id=uuid.UUID(workspace_id),
            installation_id=800_000_000 + (uuid.UUID(site_id).int % 100_000_000),
            account_id=9001,
            account_login="operator",
            account_type="Organization",
            target_type="Organization",
            repository_selection="selected",
            permissions={"contents": "write", "pull_requests": "write"},
            status="active",
            last_verified_at=datetime.now(timezone.utc),
        )
        db.add(installation)
        await db.flush()
        db.add(
            GitHubRepositoryConnection(
                workspace_id=uuid.UUID(workspace_id),
                site_id=uuid.UUID(site_id),
                installation_id=installation.id,
                github_repository_id=101,
                repository_full_name="operator/site",
                visibility="private",
                default_branch="main",
                permissions={"pull": True, "push": True},
                status="active",
                last_verified_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()


async def _github_record(action_id: str) -> GitHubExecution | None:
    async with async_session_factory() as db:
        return await db.scalar(
            select(GitHubExecution).where(
                GitHubExecution.action_id == uuid.UUID(action_id)
            )
        )


def test_governed_github_draft_pr_execution_and_safe_rollback(monkeypatch) -> None:
    suffix = uuid.uuid4().hex
    settings = get_settings()
    previous_enabled = settings.github_execution_enabled
    settings.github_execution_enabled = True
    provider = _GitHubProviderClient()
    adapter = GitHubExecutionAdapter(provider_client=provider)
    real_factory = execution_adapters.get_execution_adapter

    async def fake_installation_token(_installation_id: int, **_kwargs) -> str:
        return "ephemeral-installation-token"

    def adapter_factory(name: str):
        return adapter if name.strip().lower() == "github" else real_factory(name)

    monkeypatch.setattr(
        "app.services.github_execution_service.create_installation_token",
        fake_installation_token,
    )
    monkeypatch.setattr(execution_service, "get_execution_adapter", adapter_factory)

    try:
        with TestClient(app) as client:
            assert client.portal is not None
            client.portal.call(_reset_database_pool_for_test_loop)
            owner = _register(
                client,
                f"github-execution-{suffix}@example.com",
                f"GitHub Execution {suffix}",
            )
            headers = _headers(owner)
            site = client.post(
                "/sites",
                headers=headers,
                json={"domain": f"github-execution-{suffix}.example.com", "name": "GitHub Site"},
            )
            assert site.status_code == 201, site.text
            site_id = site.json()["id"]
            client.portal.call(
                _authorize_repository,
                owner["workspace"]["id"],
                site_id,
            )

            created = client.post(
                "/operator-actions",
                headers=headers,
                json={
                    "site_id": site_id,
                    "action_type": "content_refresh_draft",
                    "title": "Refresh the landing-page title",
                    "description": "Apply the exact reviewed content update.",
                    "evidence": [{"type": "operator_review", "approved_source": True}],
                    "plan": {"objective": "Refresh title", "steps": ["update one file"]},
                    "impact_score": 50,
                    "confidence_score": 90,
                    "effort_score": 10,
                    "risk_score": 10,
                    "execution_target": {"adapter": "github", "base_branch": "main"},
                    "proposed_diff": {
                        "commit_message": "Refresh landing-page title",
                        "files": [
                            {
                                "path": "content/page.md",
                                "operation": "update",
                                "content": "new title\n",
                                "expected_sha": OLD_BLOB_SHA,
                            }
                        ],
                    },
                    "rollback_plan": {"strategy": "close_draft_pr_and_delete_unchanged_branch"},
                    "measurement_plan": {"windows_days": [7, 14, 30]},
                    "validation_checklist": ["draft pull request remains open"],
                    "idempotency_key": f"github-execution:{suffix}",
                },
            )
            assert created.status_code == 201, created.text
            action = created.json()

            proposed = client.post(
                f"/operator-actions/{action['id']}/propose",
                headers=headers,
                json={"expected_version": action["version"]},
            )
            assert proposed.status_code == 200, proposed.text
            assert proposed.json()["status"] == "needs_approval"
            assert proposed.json()["approval_policy"]["mode"] == "manual_approval"

            approved = client.post(
                f"/operator-actions/{action['id']}/decision",
                headers=headers,
                json={"expected_version": proposed.json()["version"], "decision": "approve"},
            )
            assert approved.status_code == 200, approved.text

            queued = client.post(
                f"/operator-actions/{action['id']}/execute",
                headers=headers,
                json={"expected_version": approved.json()["version"]},
            )
            assert queued.status_code == 202, queued.text
            for _ in range(2):
                worker = client.post("/execution-jobs/worker/run-once", headers=headers)
                assert worker.status_code == 200, worker.text

            completed = client.get(f"/operator-actions/{action['id']}", headers=headers)
            assert completed.status_code == 200, completed.text
            result = completed.json()
            assert result["status"] == "succeeded"
            provider_result = result["execution_result"]["execution"]["execution"]
            assert provider_result["pull_request_url"].endswith("/pull/17")
            assert provider_result["draft"] is True
            assert provider_result["site_mutation_applied"] is False
            assert result["execution_result"]["execution"]["mutation_applied"] is False
            assert "ephemeral-installation-token" not in completed.text

            record = client.portal.call(_github_record, action["id"])
            assert record is not None
            assert record.status == "validated"
            assert record.pull_request_draft is True
            assert record.commit_sha == COMMIT_SHA

            rollback = client.post(
                f"/operator-actions/{action['id']}/rollback",
                headers=headers,
                json={"expected_version": result["version"]},
            )
            assert rollback.status_code == 202, rollback.text
            worker = client.post("/execution-jobs/worker/run-once", headers=headers)
            assert worker.status_code == 200, worker.text
            rolled_back = client.get(f"/operator-actions/{action['id']}", headers=headers)
            assert rolled_back.status_code == 200
            assert rolled_back.json()["status"] == "rolled_back"
            assert provider.branch_sha is None
            assert provider.pull_request is not None
            assert provider.pull_request["state"] == "closed"
    finally:
        settings.github_execution_enabled = previous_enabled


def test_github_execution_rejects_protected_paths_before_provider_calls() -> None:
    from app.services.github_execution_service import _file_changes, GitHubExecutionError

    for path, code in (
        (".github/workflows/release.yml", "github_protected_path"),
        ("config/.env.production", "github_protected_path"),
        ("credentials/signing.pem", "github_protected_path"),
        ("../outside.txt", "github_patch_invalid"),
    ):
        action = type(
            "Action",
            (),
            {
                "proposed_diff": {
                    "files": [
                        {"path": path, "operation": "update", "content": "unsafe"}
                    ]
                }
            },
        )()
        try:
            _file_changes(action)
        except GitHubExecutionError as exc:
            assert exc.code == code
        else:
            raise AssertionError(f"Unsafe path should be rejected: {path}")
