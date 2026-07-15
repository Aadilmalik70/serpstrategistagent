from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_factory
from app.models.execution import ExecutionAttempt, ExecutionJob, ExecutionSnapshot
from app.models.operator_action import OperatorAction, OperatorActionEvent
from app.services.execution_adapters import (
    AdapterSnapshot,
    ExecutionAdapterError,
    ExecutionAdapterUnavailable,
    ExecutionValidationFailed,
    get_execution_adapter,
)
from app.services.operator_action_service import get_action
from app.services.search_performance_service import (
    create_action_measurement_baselines,
    mark_action_measurement_mutation_applied,
    refreeze_action_measurement_baselines,
    refresh_action_measurements,
)

logger = logging.getLogger(__name__)
settings = get_settings()
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
ACTIVE_JOB_STATUSES = {"queued", "running", "retry_wait"}
TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled"}


class ExecutionServiceError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _adapter_name(action: OperatorAction) -> str:
    target = action.execution_target or {}
    return str(target.get("adapter") or target.get("provider") or target.get("type") or "").strip().lower()


def _checksum(data: dict[str, Any]) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _append_event(
    db: AsyncSession,
    action: OperatorAction,
    *,
    event_type: str,
    from_status: str | None,
    to_status: str | None,
    actor_user_id: uuid.UUID | None,
    actor_type: str = "system",
    payload: dict[str, Any] | None = None,
) -> None:
    if action.workspace_id is None:
        raise ExecutionServiceError("Action is not attached to a workspace", 409)
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


def job_to_dict(job: ExecutionJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "action_id": job.action_id,
        "workspace_id": job.workspace_id,
        "site_id": job.site_id,
        "parent_job_id": job.parent_job_id,
        "job_type": job.job_type,
        "adapter": job.adapter,
        "status": job.status,
        "priority": job.priority,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "idempotency_key": job.idempotency_key,
        "payload": job.payload or {},
        "result": job.result or {},
        "error_code": job.error_code,
        "error_message": job.error_message,
        "run_after": job.run_after,
        "lease_owner": job.lease_owner,
        "lease_expires_at": job.lease_expires_at,
        "cancellation_requested": job.cancellation_requested,
        "created_by_user_id": job.created_by_user_id,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
    }


def attempt_to_dict(attempt: ExecutionAttempt) -> dict[str, Any]:
    return {
        "id": attempt.id,
        "job_id": attempt.job_id,
        "attempt_number": attempt.attempt_number,
        "worker_id": attempt.worker_id,
        "status": attempt.status,
        "result": attempt.result or {},
        "error_code": attempt.error_code,
        "error_message": attempt.error_message,
        "started_at": attempt.started_at,
        "completed_at": attempt.completed_at,
    }


def snapshot_to_dict(snapshot: ExecutionSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.id,
        "action_id": snapshot.action_id,
        "job_id": snapshot.job_id,
        "workspace_id": snapshot.workspace_id,
        "site_id": snapshot.site_id,
        "snapshot_type": snapshot.snapshot_type,
        "adapter": snapshot.adapter,
        "external_revision": snapshot.external_revision,
        "checksum": snapshot.checksum,
        "data": snapshot.data or {},
        "created_at": snapshot.created_at,
    }


async def _signal_job(job_id: uuid.UUID) -> None:
    if not settings.redis_url:
        return
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis.rpush(settings.execution_queue_key, str(job_id))
        await redis.expire(settings.execution_queue_key, 86400)
    except Exception as exc:  # DB queue remains authoritative.
        logger.warning("Execution Redis signal failed: %s", type(exc).__name__)
    finally:
        await redis.aclose()


async def _pop_signal() -> uuid.UUID | None:
    if not settings.redis_url:
        return None
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        raw = await redis.lpop(settings.execution_queue_key)
        return uuid.UUID(raw) if raw else None
    except Exception:
        return None
    finally:
        await redis.aclose()


async def get_execution_job(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
) -> ExecutionJob:
    job = await db.scalar(
        select(ExecutionJob).where(
            ExecutionJob.id == job_id,
            ExecutionJob.workspace_id == workspace_id,
        )
    )
    if not job:
        raise ExecutionServiceError("Execution job not found", 404)
    return job


async def list_execution_jobs(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    action_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[ExecutionJob]:
    query = select(ExecutionJob).where(ExecutionJob.workspace_id == workspace_id)
    if action_id:
        query = query.where(ExecutionJob.action_id == action_id)
    if status:
        query = query.where(ExecutionJob.status == status)
    query = query.order_by(ExecutionJob.created_at.desc()).limit(limit)
    return list((await db.execute(query)).scalars().all())


async def list_job_attempts(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
) -> list[ExecutionAttempt]:
    await get_execution_job(db, workspace_id=workspace_id, job_id=job_id)
    return list(
        (
            await db.execute(
                select(ExecutionAttempt)
                .join(ExecutionJob, ExecutionJob.id == ExecutionAttempt.job_id)
                .where(
                    ExecutionAttempt.job_id == job_id,
                    ExecutionJob.workspace_id == workspace_id,
                )
                .order_by(ExecutionAttempt.attempt_number.asc())
            )
        ).scalars().all()
    )


async def list_execution_snapshots(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    job_id: uuid.UUID | None = None,
    action_id: uuid.UUID | None = None,
) -> list[ExecutionSnapshot]:
    query = select(ExecutionSnapshot).where(ExecutionSnapshot.workspace_id == workspace_id)
    if job_id:
        query = query.where(ExecutionSnapshot.job_id == job_id)
    if action_id:
        query = query.where(ExecutionSnapshot.action_id == action_id)
    query = query.order_by(ExecutionSnapshot.created_at.asc())
    return list((await db.execute(query)).scalars().all())


async def _existing_job(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    idempotency_key: str,
) -> ExecutionJob | None:
    return await db.scalar(
        select(ExecutionJob).where(
            ExecutionJob.workspace_id == workspace_id,
            ExecutionJob.idempotency_key == idempotency_key,
        )
    )


async def enqueue_execution(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    action_id: uuid.UUID,
    expected_version: int,
) -> ExecutionJob:
    action = await get_action(db, workspace_id, action_id)
    if action.version != expected_version:
        raise ExecutionServiceError("Action changed since it was loaded", 409)
    if action.status != "approved":
        raise ExecutionServiceError("Only approved actions can be queued for execution", 409)

    adapter_name = _adapter_name(action)
    try:
        adapter = get_execution_adapter(adapter_name)
        await adapter.preflight(action, db=db, operation="execute")
    except ExecutionAdapterError as exc:
        raise ExecutionServiceError(str(exc), 409) from exc

    idempotency_key = f"execute:{action.id}:{action.version}"
    existing = await _existing_job(db, workspace_id=workspace_id, idempotency_key=idempotency_key)
    if existing:
        return existing

    await create_action_measurement_baselines(db, action)

    job = ExecutionJob(
        action_id=action.id,
        workspace_id=workspace_id,
        site_id=action.site_id,
        job_type="execute",
        adapter=adapter_name,
        status="queued",
        priority=max(0, min(100, action.impact_score - action.effort_score)),
        max_attempts=settings.execution_job_max_attempts,
        idempotency_key=idempotency_key,
        payload={"action_version": action.version},
        created_by_user_id=user_id,
    )
    db.add(job)
    old_status = action.status
    action.status = "execution_queued"
    action.version += 1
    await db.flush()
    _append_event(
        db,
        action,
        event_type="action_execution_queued",
        from_status=old_status,
        to_status=action.status,
        actor_user_id=user_id,
        actor_type="user",
        payload={"job_id": str(job.id), "adapter": adapter_name},
    )
    await db.commit()
    await db.refresh(job)
    await _signal_job(job.id)
    return job


async def enqueue_rollback(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    action_id: uuid.UUID,
    expected_version: int,
) -> ExecutionJob:
    action = await get_action(db, workspace_id, action_id)
    if action.version != expected_version:
        raise ExecutionServiceError("Action changed since it was loaded", 409)
    if action.status != "succeeded":
        raise ExecutionServiceError("Only successfully executed actions can be rolled back", 409)

    adapter_name = _adapter_name(action)
    try:
        adapter = get_execution_adapter(adapter_name)
        await adapter.preflight(action, db=db, operation="rollback")
    except ExecutionAdapterError as exc:
        raise ExecutionServiceError(str(exc), 409) from exc

    before = await db.scalar(
        select(ExecutionSnapshot)
        .where(
            ExecutionSnapshot.action_id == action.id,
            ExecutionSnapshot.workspace_id == workspace_id,
            ExecutionSnapshot.snapshot_type == "before",
        )
        .order_by(ExecutionSnapshot.created_at.desc())
        .limit(1)
    )
    if not before:
        raise ExecutionServiceError("No before-state snapshot is available for rollback", 409)

    idempotency_key = f"rollback:{action.id}:{action.version}:{before.id}"
    existing = await _existing_job(db, workspace_id=workspace_id, idempotency_key=idempotency_key)
    if existing:
        return existing

    job = ExecutionJob(
        action_id=action.id,
        workspace_id=workspace_id,
        site_id=action.site_id,
        job_type="rollback",
        adapter=adapter_name,
        status="queued",
        priority=100,
        max_attempts=settings.execution_job_max_attempts,
        idempotency_key=idempotency_key,
        payload={"before_snapshot_id": str(before.id)},
        created_by_user_id=user_id,
    )
    db.add(job)
    old_status = action.status
    action.status = "rollback_queued"
    action.version += 1
    await db.flush()
    _append_event(
        db,
        action,
        event_type="action_rollback_queued",
        from_status=old_status,
        to_status=action.status,
        actor_user_id=user_id,
        actor_type="user",
        payload={"job_id": str(job.id), "before_snapshot_id": str(before.id)},
    )
    await db.commit()
    await db.refresh(job)
    await _signal_job(job.id)
    return job


async def request_job_cancellation(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
) -> ExecutionJob:
    job = await get_execution_job(db, workspace_id=workspace_id, job_id=job_id)
    if job.status in TERMINAL_JOB_STATUSES:
        return job
    job.cancellation_requested = True
    action = await get_action(db, workspace_id, job.action_id)
    if job.status in {"queued", "retry_wait"}:
        job.status = "cancelled"
        job.completed_at = _now()
        old_status = action.status
        action.status = "cancelled"
        action.version += 1
        _append_event(
            db,
            action,
            event_type="execution_job_cancelled",
            from_status=old_status,
            to_status=action.status,
            actor_user_id=user_id,
            actor_type="user",
            payload={"job_id": str(job.id), "job_type": job.job_type},
        )
    await db.commit()
    await db.refresh(job)
    return job


async def recover_expired_leases(db: AsyncSession) -> int:
    now = _now()
    jobs = list(
        (
            await db.execute(
                select(ExecutionJob)
                .where(
                    ExecutionJob.status == "running",
                    ExecutionJob.lease_expires_at.is_not(None),
                    ExecutionJob.lease_expires_at < now,
                )
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
    )
    recovered = 0
    for job in jobs:
        job.lease_owner = None
        job.lease_expires_at = None
        if job.attempt_count >= job.max_attempts:
            job.status = "failed"
            job.error_code = "lease_expired"
            job.error_message = "Execution lease expired after the final attempt"
            job.completed_at = now
        else:
            job.status = "retry_wait"
            job.run_after = now
        recovered += 1
    if recovered:
        await db.commit()
    return recovered


async def claim_next_job(
    db: AsyncSession,
    *,
    worker_id: str,
    preferred_job_id: uuid.UUID | None = None,
) -> ExecutionJob | None:
    now = _now()
    query = select(ExecutionJob).where(
        ExecutionJob.status.in_(["queued", "retry_wait"]),
        ExecutionJob.run_after <= now,
        ExecutionJob.cancellation_requested.is_(False),
    )
    if preferred_job_id:
        query = query.where(ExecutionJob.id == preferred_job_id)
    query = (
        query.order_by(ExecutionJob.priority.desc(), ExecutionJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = await db.scalar(query)
    if not job and preferred_job_id:
        return await claim_next_job(db, worker_id=worker_id, preferred_job_id=None)
    if not job:
        return None
    job.status = "running"
    job.lease_owner = worker_id
    job.lease_expires_at = now + timedelta(seconds=settings.execution_job_lease_seconds)
    job.started_at = job.started_at or now
    await db.commit()
    await db.refresh(job)
    return job


def _create_snapshot(
    db: AsyncSession,
    *,
    job: ExecutionJob,
    action: OperatorAction,
    snapshot_type: str,
    snapshot: AdapterSnapshot,
) -> ExecutionSnapshot:
    record = ExecutionSnapshot(
        action_id=action.id,
        job_id=job.id,
        workspace_id=job.workspace_id,
        site_id=job.site_id,
        snapshot_type=snapshot_type,
        adapter=job.adapter,
        external_revision=snapshot.external_revision,
        checksum=_checksum(snapshot.data),
        data=snapshot.data,
    )
    db.add(record)
    return record


async def _latest_before_snapshot(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    action_id: uuid.UUID,
) -> ExecutionSnapshot | None:
    return await db.scalar(
        select(ExecutionSnapshot)
        .where(
            ExecutionSnapshot.workspace_id == workspace_id,
            ExecutionSnapshot.action_id == action_id,
            ExecutionSnapshot.snapshot_type == "before",
        )
        .order_by(ExecutionSnapshot.created_at.desc())
        .limit(1)
    )


async def _create_validation_job(
    db: AsyncSession,
    *,
    execution_job: ExecutionJob,
    action: OperatorAction,
) -> ExecutionJob:
    idempotency_key = f"validate:{action.id}:{execution_job.id}"
    existing = await _existing_job(db, workspace_id=execution_job.workspace_id, idempotency_key=idempotency_key)
    if existing:
        return existing
    validation = ExecutionJob(
        action_id=action.id,
        workspace_id=execution_job.workspace_id,
        site_id=execution_job.site_id,
        parent_job_id=execution_job.id,
        job_type="validate",
        adapter=execution_job.adapter,
        status="queued",
        priority=execution_job.priority,
        max_attempts=execution_job.max_attempts,
        idempotency_key=idempotency_key,
        payload={"execution_job_id": str(execution_job.id)},
        created_by_user_id=execution_job.created_by_user_id,
    )
    db.add(validation)
    await db.flush()
    return validation


async def process_execution_job(
    db: AsyncSession,
    *,
    job_id: uuid.UUID,
    worker_id: str,
) -> ExecutionJob:
    job = await db.scalar(
        select(ExecutionJob).where(ExecutionJob.id == job_id).with_for_update()
    )
    if not job:
        raise ExecutionServiceError("Execution job not found", 404)
    if job.status != "running" or job.lease_owner != worker_id:
        raise ExecutionServiceError("Execution job is not leased by this worker", 409)

    action = await db.scalar(
        select(OperatorAction).where(OperatorAction.id == job.action_id).with_for_update()
    )
    if not action:
        raise ExecutionServiceError("Operator action not found", 404)

    now = _now()
    job.attempt_count += 1
    attempt = ExecutionAttempt(
        job_id=job.id,
        attempt_number=job.attempt_count,
        worker_id=worker_id,
        status="running",
    )
    db.add(attempt)
    await db.flush()

    if job.cancellation_requested:
        job.status = "cancelled"
        job.completed_at = now
        attempt.status = "cancelled"
        attempt.completed_at = now
        old_status = action.status
        action.status = "cancelled"
        action.version += 1
        _append_event(
            db,
            action,
            event_type="execution_job_cancelled",
            from_status=old_status,
            to_status=action.status,
            actor_user_id=None,
            payload={"job_id": str(job.id)},
        )
        await db.commit()
        await db.refresh(job)
        return job

    try:
        adapter = get_execution_adapter(job.adapter)
        if job.job_type == "execute":
            before = await adapter.capture(action, phase="before", db=db)
            _create_snapshot(db, job=job, action=action, snapshot_type="before", snapshot=before)
            old_status = action.status
            action.status = "executing"
            action.execution_started_at = now
            await refreeze_action_measurement_baselines(db, action)
            action.version += 1
            _append_event(
                db,
                action,
                event_type="action_execution_started",
                from_status=old_status,
                to_status=action.status,
                actor_user_id=None,
                payload={"job_id": str(job.id), "attempt": job.attempt_count, "adapter": job.adapter},
            )
            applied = await adapter.apply(action, before=before, db=db)
            action.executed_at = _now()
            mutation_applied = bool(adapter.mutation_enabled and applied.mutation_applied)
            await mark_action_measurement_mutation_applied(
                db,
                action,
                mutation_applied=mutation_applied,
            )
            job.result = {
                "execution": applied.result,
                "external_revision": applied.external_revision,
                "mutation_applied": mutation_applied,
            }
            validation_job = await _create_validation_job(db, execution_job=job, action=action)
            job.status = "succeeded"
            job.completed_at = _now()
            action.status = "validating"
            action.version += 1
            _append_event(
                db,
                action,
                event_type="action_validation_queued",
                from_status="executing",
                to_status="validating",
                actor_user_id=None,
                payload={"job_id": str(validation_job.id), "execution_job_id": str(job.id)},
            )
            attempt.result = job.result
            attempt.status = "succeeded"
            attempt.completed_at = _now()
            job.lease_owner = None
            job.lease_expires_at = None
            await db.commit()
            await db.refresh(job)
            await _signal_job(validation_job.id)
            return job

        if job.job_type == "validate":
            before_record = await _latest_before_snapshot(
                db, workspace_id=job.workspace_id, action_id=action.id
            )
            if not before_record:
                raise ExecutionValidationFailed("Before-state snapshot is missing")
            before = AdapterSnapshot(
                data=before_record.data or {},
                external_revision=before_record.external_revision,
            )
            parent = await db.get(ExecutionJob, job.parent_job_id) if job.parent_job_id else None
            execution_result = (parent.result or {}) if parent else {}
            validation = await adapter.validate(
                action,
                before=before,
                execution_result=execution_result,
                db=db,
            )
            after = await adapter.capture(action, phase="after", db=db)
            _create_snapshot(db, job=job, action=action, snapshot_type="after", snapshot=after)
            if not validation.passed:
                raise ExecutionValidationFailed(validation.summary)
            job.result = {
                "passed": True,
                "checks": validation.checks,
                "summary": validation.summary,
            }
            job.status = "succeeded"
            job.completed_at = _now()
            action.status = "succeeded"
            action.executed_at = action.executed_at or _now()
            action.completed_at = _now()
            action.execution_result = {
                "execution_job_id": str(parent.id) if parent else None,
                "validation_job_id": str(job.id),
                "execution": execution_result,
                "validation": job.result,
            }
            action.version += 1
            await refresh_action_measurements(db, action)
            _append_event(
                db,
                action,
                event_type="action_validation_succeeded",
                from_status="validating",
                to_status="succeeded",
                actor_user_id=None,
                payload={"job_id": str(job.id), "checks": validation.checks},
            )
            attempt.result = job.result
            attempt.status = "succeeded"
            attempt.completed_at = _now()
            job.lease_owner = None
            job.lease_expires_at = None
            await db.commit()
            await db.refresh(job)
            return job

        if job.job_type == "rollback":
            before_record = await _latest_before_snapshot(
                db, workspace_id=job.workspace_id, action_id=action.id
            )
            if not before_record:
                raise ExecutionAdapterError("Before-state snapshot is missing")
            before = AdapterSnapshot(
                data=before_record.data or {},
                external_revision=before_record.external_revision,
            )
            old_status = action.status
            action.status = "rolling_back"
            action.version += 1
            _append_event(
                db,
                action,
                event_type="action_rollback_started",
                from_status=old_status,
                to_status=action.status,
                actor_user_id=None,
                payload={"job_id": str(job.id)},
            )
            rolled_back = await adapter.rollback(action, before=before, db=db)
            rollback_snapshot = AdapterSnapshot(
                data={"restored": before.data, "result": rolled_back.result},
                external_revision=rolled_back.external_revision,
            )
            _create_snapshot(
                db,
                job=job,
                action=action,
                snapshot_type="rollback",
                snapshot=rollback_snapshot,
            )
            job.result = rolled_back.result
            job.status = "succeeded"
            job.completed_at = _now()
            action.status = "rolled_back"
            action.version += 1
            _append_event(
                db,
                action,
                event_type="action_rolled_back",
                from_status="rolling_back",
                to_status="rolled_back",
                actor_user_id=None,
                payload={"job_id": str(job.id), "snapshot_id": str(before_record.id)},
            )
            await refresh_action_measurements(db, action)
            attempt.result = job.result
            attempt.status = "succeeded"
            attempt.completed_at = _now()
            job.lease_owner = None
            job.lease_expires_at = None
            await db.commit()
            await db.refresh(job)
            return job

        raise ExecutionAdapterError(f"Unsupported execution job type: {job.job_type}")
    except Exception as exc:
        error_code = getattr(exc, "code", "unexpected_error")
        retryable = bool(getattr(exc, "retryable", not isinstance(exc, ExecutionAdapterUnavailable)))
        error_message = str(exc)[:2000]
        attempt.status = "failed"
        attempt.error_code = error_code
        attempt.error_message = error_message
        attempt.completed_at = _now()
        job.error_code = error_code
        job.error_message = error_message
        job.lease_owner = None
        job.lease_expires_at = None

        if retryable and job.attempt_count < job.max_attempts:
            delay = settings.execution_retry_base_seconds * (2 ** (job.attempt_count - 1))
            job.status = "retry_wait"
            job.run_after = _now() + timedelta(seconds=delay)
            old_status = action.status
            action.status = {
                "execute": "execution_queued",
                "validate": "validating",
                "rollback": "rollback_queued",
            }.get(job.job_type, action.status)
            action.version += 1
            _append_event(
                db,
                action,
                event_type="execution_retry_scheduled",
                from_status=old_status,
                to_status=action.status,
                actor_user_id=None,
                payload={
                    "job_id": str(job.id),
                    "attempt": job.attempt_count,
                    "run_after": job.run_after.isoformat(),
                    "error_code": error_code,
                },
            )
        else:
            job.status = "failed"
            job.completed_at = _now()
            old_status = action.status
            action.status = "failed"
            action.failed_at = _now()
            action.version += 1
            _append_event(
                db,
                action,
                event_type="action_execution_failed",
                from_status=old_status,
                to_status="failed",
                actor_user_id=None,
                payload={"job_id": str(job.id), "error_code": error_code},
            )
        await db.commit()
        await db.refresh(job)
        if job.status == "retry_wait":
            await _signal_job(job.id)
        return job


async def run_execution_worker_tick() -> int:
    processed = 0
    async with async_session_factory() as db:
        await recover_expired_leases(db)
    for _ in range(settings.execution_worker_batch_size):
        preferred = await _pop_signal()
        async with async_session_factory() as db:
            job = await claim_next_job(db, worker_id=WORKER_ID, preferred_job_id=preferred)
        if not job:
            break
        async with async_session_factory() as db:
            await process_execution_job(db, job_id=job.id, worker_id=WORKER_ID)
        processed += 1
    return processed
