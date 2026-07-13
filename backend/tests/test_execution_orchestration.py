import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.database import async_session_factory
from app.main import app
from app.models.execution import ExecutionJob, ExecutionSnapshot
from app.services.execution_service import claim_next_job, process_execution_job


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
        "evidence": [{"type": "crawl", "url": "https://example.com/pricing", "finding": "Title is weak"}],
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


def _create_approved_action(client: TestClient, auth: dict, site_id: str, suffix: str, adapter="simulation") -> dict:
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
    assert proposed.json()["status"] == "approved"
    return proposed.json()


@pytest.mark.asyncio
async def test_simulation_execution_validation_and_rollback_are_durable() -> None:
    suffix = uuid.uuid4().hex
    with TestClient(app) as client:
        owner = _register(client, f"execution-owner-{suffix}@example.com", "Execution Owner")
        outsider = _register(client, f"execution-outsider-{suffix}@example.com", "Execution Outsider")
        site_id = _create_site(client, owner, suffix)
        action = _create_approved_action(client, owner, site_id, suffix)

        queued = client.post(
            f"/operator-actions/{action['id']}/execute",
            headers=_headers(owner),
            json={"expected_version": action["version"]},
        )
        assert queued.status_code == 202, queued.text
        execution_job = queued.json()
        assert execution_job["status"] == "queued"
        assert execution_job["adapter"] == "simulation"

        outsider_read = client.get(
            f"/execution-jobs/{execution_job['id']}",
            headers=_headers(outsider),
        )
        assert outsider_read.status_code == 404

    worker_id = f"test-worker-{suffix}"
    async with async_session_factory() as db:
        claimed = await claim_next_job(
            db,
            worker_id=worker_id,
            preferred_job_id=uuid.UUID(execution_job["id"]),
        )
        assert claimed is not None
        assert claimed.status == "running"
    async with async_session_factory() as db:
        completed_execution = await process_execution_job(
            db,
            job_id=uuid.UUID(execution_job["id"]),
            worker_id=worker_id,
        )
        assert completed_execution.status == "succeeded"

    async with async_session_factory() as db:
        validation = await db.scalar(
            select(ExecutionJob).where(
                ExecutionJob.parent_job_id == uuid.UUID(execution_job["id"]),
                ExecutionJob.job_type == "validate",
            )
        )
        assert validation is not None
        validation_id = validation.id
        claimed_validation = await claim_next_job(
            db,
            worker_id=worker_id,
            preferred_job_id=validation_id,
        )
        assert claimed_validation is not None
    async with async_session_factory() as db:
        completed_validation = await process_execution_job(
            db,
            job_id=validation_id,
            worker_id=worker_id,
        )
        assert completed_validation.status == "succeeded"

    with TestClient(app) as client:
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
        assert job_detail.json()["attempts"][0]["status"] == "succeeded"
        assert any(item["snapshot_type"] == "before" for item in job_detail.json()["snapshots"])

        rollback = client.post(
            f"/operator-actions/{action['id']}/rollback",
            headers=_headers(owner),
            json={"expected_version": succeeded_action["version"]},
        )
        assert rollback.status_code == 202, rollback.text
        rollback_job = rollback.json()

    async with async_session_factory() as db:
        claimed_rollback = await claim_next_job(
            db,
            worker_id=worker_id,
            preferred_job_id=uuid.UUID(rollback_job["id"]),
        )
        assert claimed_rollback is not None
    async with async_session_factory() as db:
        completed_rollback = await process_execution_job(
            db,
            job_id=uuid.UUID(rollback_job["id"]),
            worker_id=worker_id,
        )
        assert completed_rollback.status == "succeeded"

    with TestClient(app) as client:
        rolled_back = client.get(
            f"/operator-actions/{action['id']}",
            headers=_headers(owner),
        )
        assert rolled_back.status_code == 200
        assert rolled_back.json()["status"] == "rolled_back"


@pytest.mark.asyncio
async def test_disabled_adapter_and_queued_cancellation_are_safe() -> None:
    suffix = uuid.uuid4().hex
    with TestClient(app) as client:
        owner = _register(client, f"disabled-owner-{suffix}@example.com", "Disabled Adapter")
        site_id = _create_site(client, owner, f"disabled-{suffix}")
        github_action = _create_approved_action(client, owner, site_id, f"github-{suffix}", adapter="github")

        blocked_execution = client.post(
            f"/operator-actions/{github_action['id']}/execute",
            headers=_headers(owner),
            json={"expected_version": github_action["version"]},
        )
        assert blocked_execution.status_code == 409
        assert "not enabled for mutations" in blocked_execution.json()["detail"]

        simulation_action = _create_approved_action(client, owner, site_id, f"cancel-{suffix}")
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


@pytest.mark.asyncio
async def test_execution_snapshots_are_append_only() -> None:
    snapshot_id = await _latest_snapshot_id()
    if snapshot_id is None:
        pytest.skip("Execution lifecycle test did not create a snapshot")

    async with async_session_factory() as db:
        with pytest.raises(Exception):
            await db.execute(
                text("UPDATE execution_snapshots SET snapshot_type = 'tampered' WHERE id = :id"),
                {"id": snapshot_id},
            )
            await db.commit()
        await db.rollback()

        with pytest.raises(Exception):
            await db.execute(
                text("DELETE FROM execution_snapshots WHERE id = :id"),
                {"id": snapshot_id},
            )
            await db.commit()
        await db.rollback()


async def _latest_snapshot_id() -> uuid.UUID | None:
    async with async_session_factory() as db:
        return await db.scalar(
            select(ExecutionSnapshot.id).order_by(ExecutionSnapshot.created_at.desc()).limit(1)
        )
