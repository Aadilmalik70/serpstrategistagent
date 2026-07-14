from datetime import datetime, timezone
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.issue import Issue
from app.models.operator_action import OperatorAction, OperatorActionEvent
from app.models.site import Site
from app.schemas.operator_action import OperatorActionCreate
from app.services.action_policy_service import evaluate_action_policy


class OperatorActionServiceError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


TERMINAL_STATUSES = {"rejected", "blocked", "succeeded", "failed", "cancelled", "rolled_back"}


def action_to_dict(action: OperatorAction) -> dict[str, Any]:
    return {
        "id": action.id,
        "workspace_id": action.workspace_id,
        "site_id": action.site_id,
        "issue_id": action.issue_id,
        "action_type": action.action_type,
        "category": action.category,
        "source": action.source,
        "status": action.status,
        "title": action.title,
        "description": action.description,
        "evidence": action.evidence or [],
        "plan": action.plan or {},
        "impact_score": action.impact_score,
        "confidence_score": action.confidence_score,
        "effort_score": action.effort_score,
        "risk_score": action.risk_score,
        "risk_level": action.risk_level,
        "approval_policy": action.approval_policy or {},
        "requires_approval": action.requires_approval,
        "execution_target": action.execution_target or {},
        "proposed_diff": action.proposed_diff or {},
        "rollback_plan": action.rollback_plan or {},
        "measurement_plan": action.measurement_plan or {},
        "validation_checklist": action.validation_checklist or [],
        "execution_result": action.execution_result,
        "idempotency_key": action.idempotency_key,
        "version": action.version,
        "created_by_user_id": action.created_by_user_id,
        "approved_by_user_id": action.approved_by_user_id,
        "rejected_by_user_id": action.rejected_by_user_id,
        "rejection_reason": action.rejection_reason,
        "created_at": action.created_at,
        "updated_at": action.updated_at,
        "proposed_at": action.proposed_at,
        "approved_at": action.approved_at,
        "rejected_at": action.rejected_at,
        "execution_started_at": action.execution_started_at,
        "executed_at": action.executed_at,
        "completed_at": action.completed_at,
        "failed_at": action.failed_at,
    }


def event_to_dict(event: OperatorActionEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "action_id": event.action_id,
        "event_type": event.event_type,
        "from_status": event.from_status,
        "to_status": event.to_status,
        "actor_user_id": event.actor_user_id,
        "actor_type": event.actor_type,
        "payload": event.payload or {},
        "created_at": event.created_at,
    }


async def _require_site(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    site_id: uuid.UUID,
) -> Site:
    site = await db.scalar(
        select(Site).where(Site.id == site_id, Site.workspace_id == workspace_id)
    )
    if not site:
        raise OperatorActionServiceError("Site not found in this workspace", 404)
    return site


async def _require_issue(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    site_id: uuid.UUID,
    issue_id: uuid.UUID | None,
) -> Issue | None:
    if issue_id is None:
        return None
    issue = await db.scalar(
        select(Issue)
        .join(Site, Site.id == Issue.site_id)
        .where(
            Issue.id == issue_id,
            Issue.site_id == site_id,
            Site.workspace_id == workspace_id,
        )
    )
    if not issue:
        raise OperatorActionServiceError("Issue not found for this site and workspace", 404)
    return issue


async def get_action(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    action_id: uuid.UUID,
) -> OperatorAction:
    action = await db.scalar(
        select(OperatorAction).where(
            OperatorAction.id == action_id,
            OperatorAction.workspace_id == workspace_id,
        )
    )
    if not action:
        raise OperatorActionServiceError("Operator action not found", 404)
    return action


def _assert_version(action: OperatorAction, expected_version: int) -> None:
    if action.version != expected_version:
        raise OperatorActionServiceError(
            f"Action changed since it was loaded. Expected version {expected_version}, current version {action.version}.",
            409,
        )


def _append_event(
    db: AsyncSession,
    action: OperatorAction,
    *,
    event_type: str,
    from_status: str | None,
    to_status: str | None,
    actor_user_id: uuid.UUID | None,
    actor_type: str = "user",
    payload: dict[str, Any] | None = None,
) -> None:
    if action.workspace_id is None:
        raise OperatorActionServiceError("Action is not attached to a workspace", 409)
    db.add(
        OperatorActionEvent(
            action_id=action.id,
            workspace_id=action.workspace_id,
            site_id=action.site_id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            payload=payload or {},
        )
    )


async def create_action(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID | None,
    data: OperatorActionCreate,
) -> OperatorAction:
    await _require_site(db, workspace_id, data.site_id)
    await _require_issue(db, workspace_id, data.site_id, data.issue_id)

    if data.idempotency_key:
        existing = await db.scalar(
            select(OperatorAction).where(
                OperatorAction.workspace_id == workspace_id,
                OperatorAction.idempotency_key == data.idempotency_key,
            )
        )
        if existing:
            return existing

    action = OperatorAction(
        workspace_id=workspace_id,
        site_id=data.site_id,
        issue_id=data.issue_id,
        action_type=data.action_type,
        category=data.category,
        source=data.source,
        status="draft",
        title=data.title,
        description=data.description,
        evidence=data.evidence,
        plan=data.plan,
        impact_score=data.impact_score,
        confidence_score=data.confidence_score,
        effort_score=data.effort_score,
        risk_score=data.risk_score,
        execution_target=data.execution_target,
        proposed_diff=data.proposed_diff,
        rollback_plan=data.rollback_plan,
        measurement_plan=data.measurement_plan,
        validation_checklist=data.validation_checklist,
        idempotency_key=data.idempotency_key,
        created_by_user_id=user_id,
    )
    db.add(action)
    await db.flush()
    _append_event(
        db,
        action,
        event_type="action_created",
        from_status=None,
        to_status="draft",
        actor_user_id=user_id,
        actor_type="system" if user_id is None else "user",
        payload={"source": action.source, "action_type": action.action_type},
    )
    await db.commit()
    await db.refresh(action)
    return action


async def list_actions(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    site_id: uuid.UUID | None = None,
    status: str | None = None,
    risk_level: str | None = None,
    limit: int = 50,
) -> tuple[list[OperatorAction], dict[str, int], dict[str, int]]:
    query = select(OperatorAction).where(OperatorAction.workspace_id == workspace_id)
    if site_id:
        query = query.where(OperatorAction.site_id == site_id)
    if status:
        query = query.where(OperatorAction.status == status)
    if risk_level:
        query = query.where(OperatorAction.risk_level == risk_level)
    query = query.order_by(OperatorAction.created_at.desc()).limit(limit)
    items = list((await db.execute(query)).scalars().all())

    all_rows = list(
        (
            await db.execute(
                select(OperatorAction.status, OperatorAction.risk_level).where(
                    OperatorAction.workspace_id == workspace_id
                )
            )
        ).all()
    )
    counts_by_status: dict[str, int] = {}
    counts_by_risk: dict[str, int] = {}
    for row_status, row_risk in all_rows:
        counts_by_status[row_status] = counts_by_status.get(row_status, 0) + 1
        counts_by_risk[row_risk] = counts_by_risk.get(row_risk, 0) + 1
    return items, counts_by_status, counts_by_risk


async def list_events(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    action_id: uuid.UUID,
) -> list[OperatorActionEvent]:
    await get_action(db, workspace_id, action_id)
    return list(
        (
            await db.execute(
                select(OperatorActionEvent)
                .where(
                    OperatorActionEvent.action_id == action_id,
                    OperatorActionEvent.workspace_id == workspace_id,
                )
                .order_by(OperatorActionEvent.created_at.asc())
            )
        ).scalars().all()
    )


async def propose_action(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID | None,
    action_id: uuid.UUID,
    expected_version: int,
) -> OperatorAction:
    action = await get_action(db, workspace_id, action_id)
    _assert_version(action, expected_version)
    if action.status != "draft":
        raise OperatorActionServiceError("Only draft actions can be proposed", 409)

    decision = evaluate_action_policy(
        action_type=action.action_type,
        submitted_risk_score=action.risk_score,
        execution_target=action.execution_target or {},
        proposed_diff=action.proposed_diff or {},
    )
    old_status = action.status
    now = datetime.now(timezone.utc)
    action.risk_score = decision.risk_score
    action.risk_level = decision.risk_level
    action.approval_policy = decision.as_dict()
    action.requires_approval = decision.requires_approval
    action.proposed_at = now

    if decision.mode == "blocked":
        action.status = "blocked"
        event_type = "action_blocked"
    elif decision.mode == "auto_approve":
        action.status = "approved"
        action.approved_at = now
        event_type = "action_auto_approved"
    else:
        action.status = "needs_approval"
        event_type = "action_proposed"

    action.version += 1
    _append_event(
        db,
        action,
        event_type=event_type,
        from_status=old_status,
        to_status=action.status,
        actor_user_id=user_id,
        actor_type="system" if user_id is None or decision.mode in {"blocked", "auto_approve"} else "user",
        payload={"policy": decision.as_dict()},
    )
    await db.commit()
    await db.refresh(action)
    return action


async def decide_action(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID | None,
    user_role: str,
    action_id: uuid.UUID,
    expected_version: int,
    decision: str,
    reason: str | None,
) -> OperatorAction:
    action = await get_action(db, workspace_id, action_id)
    _assert_version(action, expected_version)
    if action.status != "needs_approval":
        raise OperatorActionServiceError("Only actions awaiting approval can be decided", 409)

    allowed_roles = set((action.approval_policy or {}).get("allowed_roles", []))
    if user_role not in allowed_roles:
        raise OperatorActionServiceError("Your workspace role cannot approve this action", 403)

    old_status = action.status
    now = datetime.now(timezone.utc)
    if decision == "approve":
        action.status = "approved"
        action.approved_by_user_id = user_id
        action.approved_at = now
        event_type = "action_approved"
    elif decision == "reject":
        action.status = "rejected"
        action.rejected_by_user_id = user_id
        action.rejected_at = now
        action.rejection_reason = (reason or "").strip()
        event_type = "action_rejected"
    else:
        raise OperatorActionServiceError("Unsupported decision")

    action.version += 1
    _append_event(
        db,
        action,
        event_type=event_type,
        from_status=old_status,
        to_status=action.status,
        actor_user_id=user_id,
        payload={"reason": reason} if reason else {},
    )
    await db.commit()
    await db.refresh(action)
    return action


async def cancel_action(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID | None,
    action_id: uuid.UUID,
    expected_version: int,
) -> OperatorAction:
    action = await get_action(db, workspace_id, action_id)
    _assert_version(action, expected_version)
    if action.status in TERMINAL_STATUSES or action.status == "executing":
        raise OperatorActionServiceError("This action can no longer be cancelled", 409)

    old_status = action.status
    action.status = "cancelled"
    action.version += 1
    _append_event(
        db,
        action,
        event_type="action_cancelled",
        from_status=old_status,
        to_status="cancelled",
        actor_user_id=user_id,
        actor_type="system" if user_id is None else "user",
    )
    await db.commit()
    await db.refresh(action)
    return action
