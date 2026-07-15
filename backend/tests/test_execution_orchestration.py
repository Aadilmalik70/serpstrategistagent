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


def _create_site(client: TestClient, auth: dict, suffix: str) -> str:
    response = client.post(
        "/sites",
        headers=_headers(auth),
        json={"domain": f"execution-{suffix}.example.com", "name": "Execution Test"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _action_payload(site_id: str, suffix: str, adapter: str = "simulation") -> dict:
    return {
        "site_id": site_id,
        "action_type": "metadata_update",
        "category": "technical",
        "source": "execution_test",
        "title": "Update one page title safely",
        "description": "Exercise the durable governed execution lifecycle.",
        "evidence": [
            {
                "type": "crawl",
                "url": "https://example.com/pricing",
                "finding": "Title is weak",
            }
        ],
        "plan": {"steps": ["capture", "apply", "validate"]},
        "impact_score": 80,
        "confidence_score": 90,
        "effort_score": 10,
        "risk_score": 5,
        "execution_target": {"adapter": adapter, "path": "app/pricing/page.tsx"},
        "proposed_diff": {"affected_pages": 1, "title": "Pricing for AI Growth Teams"},
        "rollback_plan": {"strategy": "restore_before_snapshot"},
        "measurement_plan": {"metrics": ["ctr"], "window_days": 14},
        "validation_checklist": ["title rendered", "page indexable"],
        "idempotency_key": f"execution-{suffix}-{adapter}",
    }


def _create_approved_action(
    client: TestClient,
    auth: dict,
    site_id: str,
    suffix: str,
    adapter: str = "simulation",
) -> dict:
    created = client.post(
        "/operator-actions",
        headers=_headers(auth),
        json=_action_payload(site_id, suffix, adapter),
    )
    assert created.status_code == 201, created.text
    proposed = client.post(
        f"/operator-actions/{created.json()['id']}/propose",
        headers=_headers(auth),
        json={"expected_version": created.json()["version"]},
    )
    assert proposed.status_code == 200, proposed.text
    proposed_action = proposed.json()
    if proposed_action["status"] == "needs_approval":
        approved = client.post(
            f"/operator-actions/{created.json()['id']}/decision",
            headers=_headers(auth),
            json={
                "expected_version": proposed_action["version"],
                "decision": "approve",
            },
        )
        assert approved.status_code == 200, approved.text
        proposed_action = approved.json()
    assert proposed_action["status"] == "approved"
    return proposed_action


def _run_worker(client: TestClient, auth: dict, times: int = 1) -> int:
    processed = 0
    for _ in range(times):
        response = client.post(
            "/execution-jobs/worker/run-once",
            headers=_headers(auth),
        )
        assert response.status_code == 200, response.text
        processed += response.json()["processed"]
    return processed


def test_simulation_execution_validation_and_rollback_are_durable() -> None:
    suffix = uuid.uuid4().hex
    with TestClient(app) as client:
        owner = _register(client, f"execution-owner-{suffix}@example.com", "Execution Owner")
        outsider = _register(client, f"execution-outsider-{suffix}@example.com", "Execution Outsider")
        site_id = _create_site(client, owner, suffix)
        action = _create_approved_action(
            client,
            owner,
            site_id,
            suffix,
            adapter="Simulation",
        )

        queued = client.post(
            f"/operator-actions/{action['id']}/execute",
            headers=_headers(owner),
            json={"expected_version": action["version"]},
        )
        assert queued.status_code == 202, queued.text
        execution_job = queued.json()
        assert execution_job["status"] == "queued"
        assert execution_job["adapter"] == "simulation"

        measurements = client.get(
            f"/operator-actions/{action['id']}/measurements",
            headers=_headers(owner),
        )
        assert measurements.status_code == 200, measurements.text
        assert measurements.json() == []

        duplicate = client.post(
            f"/operator-actions/{action['id']}/execute",
            headers=_headers(owner),
            json={"expected_version": action["version"]},
        )
        assert duplicate.status_code == 409

        outsider_read = client.get(
            f"/execution-jobs/{execution_job['id']}",
            headers=_headers(outsider),
        )
        assert outsider_read.status_code == 404

        assert _run_worker(client, owner, times=2) >= 2

        action_detail = client.get(
            f"/operator-actions/{action['id']}",
            headers=_headers(owner),
        )
        assert action_detail.status_code == 200, action_detail.text
        succeeded_action = action_detail.json()
        assert succeeded_action["status"] == "succeeded"
        assert succeeded_action["execution_result"]["validation"]["passed"] is True
        event_types = [event["event_type"] for event in succeeded_action["events"]]
        assert "action_execution_queued" in event_types
        assert "action_execution_started" in event_types
        assert "action_validation_queued" in event_types
        assert "action_validation_succeeded" in event_types

        job_detail = client.get(
            f"/execution-jobs/{execution_job['id']}",
            headers=_headers(owner),
        )
        assert job_detail.status_code == 200, job_detail.text
        execution_detail = job_detail.json()
        assert execution_detail["result"]["mutation_applied"] is False
        assert execution_detail["attempts"][0]["status"] == "succeeded"
        before_snapshot = next(
            item for item in execution_detail["snapshots"] if item["snapshot_type"] == "before"
        )
        immutability = client.post(
            f"/execution-jobs/test/snapshot-immutability/{before_snapshot['id']}",
            headers=_headers(owner),
        )
        assert immutability.status_code == 200, immutability.text
        assert immutability.json() == {"update_blocked": True, "delete_blocked": True}

        jobs = client.get(
            f"/execution-jobs?action_id={action['id']}",
            headers=_headers(owner),
        )
        assert jobs.status_code == 200
        assert {job["job_type"] for job in jobs.json()} == {"execute", "validate"}

        rollback = client.post(
            f"/operator-actions/{action['id']}/rollback",
            headers=_headers(owner),
            json={"expected_version": succeeded_action["version"]},
        )
        assert rollback.status_code == 202, rollback.text
        rollback_job = rollback.json()
        assert rollback_job["job_type"] == "rollback"

        assert _run_worker(client, owner, times=1) >= 1

        rolled_back = client.get(
            f"/operator-actions/{action['id']}",
            headers=_headers(owner),
        )
        assert rolled_back.status_code == 200
        assert rolled_back.json()["status"] == "rolled_back"

        rollback_detail = client.get(
            f"/execution-jobs/{rollback_job['id']}",
            headers=_headers(owner),
        )
        assert rollback_detail.status_code == 200
        assert any(
            snapshot["snapshot_type"] == "rollback"
            for snapshot in rollback_detail.json()["snapshots"]
        )


def test_disabled_adapter_and_queued_cancellation_are_safe() -> None:
    suffix = uuid.uuid4().hex
    with TestClient(app) as client:
        owner = _register(client, f"disabled-owner-{suffix}@example.com", "Disabled Adapter")
        site_id = _create_site(client, owner, f"disabled-{suffix}")
        github_action = _create_approved_action(
            client,
            owner,
            site_id,
            f"github-{suffix}",
            adapter="github",
        )

        blocked_execution = client.post(
            f"/operator-actions/{github_action['id']}/execute",
            headers=_headers(owner),
            json={"expected_version": github_action["version"]},
        )
        assert blocked_execution.status_code == 409
        assert "not enabled for mutations" in blocked_execution.json()["detail"]

        simulation_action = _create_approved_action(
            client,
            owner,
            site_id,
            f"cancel-{suffix}",
        )
        queued = client.post(
            f"/operator-actions/{simulation_action['id']}/execute",
            headers=_headers(owner),
            json={"expected_version": simulation_action["version"]},
        )
        assert queued.status_code == 202
        cancelled = client.post(
            f"/execution-jobs/{queued.json()['id']}/cancel",
            headers=_headers(owner),
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"

        action_after_cancel = client.get(
            f"/operator-actions/{simulation_action['id']}",
            headers=_headers(owner),
        )
        assert action_after_cancel.status_code == 200
        assert action_after_cancel.json()["status"] == "cancelled"
