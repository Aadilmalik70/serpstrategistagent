import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import async_session_factory
from app.main import app
from app.services.action_policy_service import evaluate_action_policy


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
        json={"domain": f"actions-{suffix}.example.com", "name": "Action Test Site"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _payload(site_id: str, *, action_type: str, risk_score: int, key: str, target=None, diff=None) -> dict:
    return {
        "site_id": site_id,
        "action_type": action_type,
        "category": "technical",
        "source": "test",
        "title": f"Test {action_type}",
        "description": "Evidence-backed action created by the Phase 3 lifecycle test.",
        "evidence": [
            {
                "type": "crawl_finding",
                "url": "https://example.com/page",
                "observation": "A deterministic issue was detected",
            }
        ],
        "plan": {"steps": ["capture before state", "apply minimal change", "validate"]},
        "impact_score": 72,
        "confidence_score": 88,
        "effort_score": 20,
        "risk_score": risk_score,
        "execution_target": target or {"adapter": "simulation", "path": "app/page.tsx"},
        "proposed_diff": diff or {"affected_pages": 1, "summary": "Update metadata"},
        "rollback_plan": {"strategy": "revert_commit", "required": True},
        "measurement_plan": {"window_days": [7, 14, 30], "metrics": ["clicks", "ctr"]},
        "validation_checklist": ["build passes", "canonical unchanged", "page remains indexable"],
        "idempotency_key": key,
    }


def test_policy_engine_blocks_protected_paths_and_scales_broad_changes() -> None:
    blocked = evaluate_action_policy(
        action_type="metadata_update",
        submitted_risk_score=5,
        execution_target={"path": ".github/workflows/deploy.yml"},
        proposed_diff={"affected_pages": 1},
    )
    assert blocked.mode == "blocked"
    assert blocked.risk_score >= 90
    assert blocked.allowed_roles == ("owner",)

    high = evaluate_action_policy(
        action_type="canonical_bulk",
        submitted_risk_score=10,
        execution_target={"path": "app/catalog/page.tsx"},
        proposed_diff={"affected_pages": 250},
    )
    assert high.mode == "manual_approval"
    assert high.risk_level == "high"
    assert high.allowed_roles == ("owner",)

    low = evaluate_action_policy(
        action_type="metadata_update",
        submitted_risk_score=10,
        execution_target={"path": "app/page.tsx"},
        proposed_diff={"affected_pages": 1},
    )
    assert low.mode == "auto_approve"
    assert low.requires_approval is False


def test_governed_action_lifecycle_is_idempotent_and_tenant_isolated() -> None:
    suffix = uuid.uuid4().hex
    with TestClient(app) as client:
        owner = _register(client, f"action-owner-{suffix}@example.com", "Action Owner")
        outsider = _register(client, f"action-outsider-{suffix}@example.com", "Action Outsider")
        site_id = _create_site(client, owner, suffix)

        low_payload = _payload(
            site_id,
            action_type="metadata_update",
            risk_score=10,
            key=f"metadata-{suffix}",
        )
        created = client.post("/operator-actions", headers=_headers(owner), json=low_payload)
        assert created.status_code == 201, created.text
        action = created.json()
        assert action["status"] == "draft"
        assert action["version"] == 1

        duplicate = client.post("/operator-actions", headers=_headers(owner), json=low_payload)
        assert duplicate.status_code == 201
        assert duplicate.json()["id"] == action["id"]

        proposed = client.post(
            f"/operator-actions/{action['id']}/propose",
            headers=_headers(owner),
            json={"expected_version": 1},
        )
        assert proposed.status_code == 200, proposed.text
        assert proposed.json()["status"] == "approved"
        assert proposed.json()["requires_approval"] is False
        assert proposed.json()["approval_policy"]["mode"] == "auto_approve"
        assert proposed.json()["version"] == 2

        stale = client.post(
            f"/operator-actions/{action['id']}/cancel",
            headers=_headers(owner),
            json={"expected_version": 1},
        )
        assert stale.status_code == 409

        outsider_read = client.get(
            f"/operator-actions/{action['id']}",
            headers=_headers(outsider),
        )
        assert outsider_read.status_code == 404

        detail = client.get(
            f"/operator-actions/{action['id']}",
            headers=_headers(owner),
        )
        assert detail.status_code == 200
        event_types = [event["event_type"] for event in detail.json()["events"]]
        assert event_types == ["action_created", "action_auto_approved"]

        queue = client.get("/operator-actions", headers=_headers(owner))
        assert queue.status_code == 200
        assert queue.json()["total"] == 1
        assert queue.json()["counts_by_status"]["approved"] == 1
        assert queue.json()["counts_by_risk"]["low"] == 1

        legacy = client.post(
            f"/actions/fix/{action['id']}/execute",
            headers=_headers(owner),
        )
        assert legacy.status_code == 410


def test_manual_approval_and_policy_blocking() -> None:
    suffix = uuid.uuid4().hex
    with TestClient(app) as client:
        owner = _register(client, f"decision-owner-{suffix}@example.com", "Decision Owner")
        site_id = _create_site(client, owner, f"decision-{suffix}")

        medium = client.post(
            "/operator-actions",
            headers=_headers(owner),
            json=_payload(
                site_id,
                action_type="recommendation",
                risk_score=45,
                key=f"medium-{suffix}",
            ),
        )
        assert medium.status_code == 201, medium.text
        medium_action = medium.json()

        proposed = client.post(
            f"/operator-actions/{medium_action['id']}/propose",
            headers=_headers(owner),
            json={"expected_version": 1},
        )
        assert proposed.status_code == 200
        assert proposed.json()["status"] == "needs_approval"
        assert proposed.json()["approval_policy"]["allowed_roles"] == ["owner", "admin"]

        approved = client.post(
            f"/operator-actions/{medium_action['id']}/decision",
            headers=_headers(owner),
            json={"expected_version": 2, "decision": "approve"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        assert approved.json()["approved_by_user_id"] is not None

        blocked = client.post(
            "/operator-actions",
            headers=_headers(owner),
            json=_payload(
                site_id,
                action_type="metadata_update",
                risk_score=5,
                key=f"blocked-{suffix}",
                target={"adapter": "github", "path": "robots.txt"},
            ),
        )
        assert blocked.status_code == 201
        blocked_action = blocked.json()
        blocked_proposal = client.post(
            f"/operator-actions/{blocked_action['id']}/propose",
            headers=_headers(owner),
            json={"expected_version": 1},
        )
        assert blocked_proposal.status_code == 200
        assert blocked_proposal.json()["status"] == "blocked"
        assert blocked_proposal.json()["approval_policy"]["mode"] == "blocked"

        missing_reason = client.post(
            f"/operator-actions/{blocked_action['id']}/decision",
            headers=_headers(owner),
            json={"expected_version": 2, "decision": "reject"},
        )
        assert missing_reason.status_code == 422


@pytest.mark.asyncio
async def test_action_events_table_rejects_updates_and_deletes() -> None:
    suffix = uuid.uuid4().hex
    action_id: str
    with TestClient(app) as client:
        owner = _register(client, f"append-owner-{suffix}@example.com", "Append Owner")
        site_id = _create_site(client, owner, f"append-{suffix}")
        created = client.post(
            "/operator-actions",
            headers=_headers(owner),
            json=_payload(
                site_id,
                action_type="metadata_update",
                risk_score=5,
                key=f"append-{suffix}",
            ),
        )
        assert created.status_code == 201, created.text
        action_id = created.json()["id"]

    async with async_session_factory() as db:
        with pytest.raises(Exception):
            await db.execute(
                text(
                    "UPDATE operator_action_events SET event_type = 'tampered' "
                    "WHERE action_id = CAST(:action_id AS uuid)"
                ),
                {"action_id": action_id},
            )
            await db.commit()
        await db.rollback()

        with pytest.raises(Exception):
            await db.execute(
                text(
                    "DELETE FROM operator_action_events "
                    "WHERE action_id = CAST(:action_id AS uuid)"
                ),
                {"action_id": action_id},
            )
            await db.commit()
        await db.rollback()
