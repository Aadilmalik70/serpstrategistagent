from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_factory
from app.models.agent_run import AgentRun
from app.models.identity import Workspace
from app.models.job_queue import CrawlAttempt, CrawlFrontier, JobQueue
from app.models.page import Page
from app.models.site import Site
from app.services.agent_graph import run_agent_graph
from app.services.crawler import run_crawl
from app.services.entitlement_service import (
    QuotaExceededError,
    assert_usage_quota,
    effective_entitlements,
    record_usage,
)
from app.services.first_party_crawler import CrawlLeaseLost


logger = logging.getLogger(__name__)
settings = get_settings()
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:crawl:{uuid.uuid4().hex[:8]}"
ACTIVE_CRAWL_STATUSES = {"queued", "running", "retry_wait"}
TERMINAL_CRAWL_STATUSES = {"completed", "failed", "cancelled"}


class CrawlJobServiceError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _job_workspace_id(job: JobQueue) -> uuid.UUID:
    value = (job.payload or {}).get("workspace_id")
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise CrawlJobServiceError("Crawl job workspace is invalid", 409) from exc


async def _signal_job(job_id: uuid.UUID) -> None:
    if not settings.redis_url:
        return
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis.rpush(settings.crawl_queue_key, str(job_id))
        await redis.expire(settings.crawl_queue_key, 86400)
    except Exception as exc:  # PostgreSQL polling remains authoritative.
        logger.warning("Crawl Redis signal failed: %s", type(exc).__name__)
    finally:
        await redis.aclose()


async def _pop_signal() -> uuid.UUID | None:
    if not settings.redis_url:
        return None
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        value = await redis.lpop(settings.crawl_queue_key)
        return uuid.UUID(value) if value else None
    except Exception:
        return None
    finally:
        await redis.aclose()


async def enqueue_crawl_job(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    site: Site,
    max_pages: int,
    source: str,
    agent_run_id: uuid.UUID | None = None,
    priority: int = 0,
) -> tuple[JobQueue, bool]:
    # Serialize workspace capacity reservations before the per-site singleton
    # decision. Active job max_pages values are durable reservations; terminal
    # jobs disappear from the reservation sum as their actual usage is posted.
    workspace = await db.scalar(
        select(Workspace).where(Workspace.id == workspace_id).with_for_update()
    )
    if not workspace:
        raise CrawlJobServiceError("Crawl workspace not found", 404)

    # The partial unique index is the final per-site invariant; this row lock
    # lets concurrent callers reuse the winner without a constraint error.
    locked_site = await db.scalar(
        select(Site).where(Site.id == site.id).with_for_update()
    )
    if not locked_site or locked_site.workspace_id != workspace_id:
        raise CrawlJobServiceError("Crawl site is outside this workspace", 404)
    site = locked_site
    active = await db.scalar(
        select(JobQueue)
        .where(
            JobQueue.site_id == site.id,
            JobQueue.job_type == "crawl",
            JobQueue.status.in_(ACTIVE_CRAWL_STATUSES),
        )
        .order_by(JobQueue.created_at.desc())
        .limit(1)
    )
    if active:
        if agent_run_id:
            active.payload = {**(active.payload or {}), "agent_run_id": str(agent_run_id)}
            await db.commit()
            await db.refresh(active)
        return active, True

    subscription, _, current = await assert_usage_quota(
        db,
        workspace_id=workspace_id,
        metric="monthly_crawl_pages",
        requested=1,
    )
    active_reservations = list(
        (
            await db.execute(
                select(JobQueue)
                .join(Site, Site.id == JobQueue.site_id)
                .where(
                    Site.workspace_id == workspace_id,
                    JobQueue.job_type == "crawl",
                    JobQueue.status.in_(ACTIVE_CRAWL_STATUSES),
                )
            )
        ).scalars().all()
    )
    reserved = sum(
        max(0, int((reserved_job.payload or {}).get("max_pages") or 0))
        for reserved_job in active_reservations
    )
    limit = int(effective_entitlements(subscription)["monthly_crawl_pages"])
    available = max(0, limit - current - reserved)
    bounded_max_pages = min(max(1, int(max_pages)), available)
    if bounded_max_pages < 1:
        raise QuotaExceededError("monthly_crawl_pages", limit, current + reserved, 1)

    job = JobQueue(
        site_id=site.id,
        job_type="crawl",
        status="queued",
        priority=priority,
        max_attempts=settings.crawl_job_max_attempts,
        run_after=_now(),
        payload={
            "adapter": "first_party",
            "max_pages": bounded_max_pages,
            "workspace_id": str(workspace_id),
            "source": source,
            "retry_cycle_started_at_attempt": 0,
            **({"agent_run_id": str(agent_run_id)} if agent_run_id else {}),
        },
    )
    db.add(job)
    site.status = "crawl_queued"
    await db.commit()
    await db.refresh(job)
    await _signal_job(job.id)
    return job, False


async def get_crawl_job(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
    for_update: bool = False,
) -> JobQueue:
    query = (
        select(JobQueue)
        .join(Site, Site.id == JobQueue.site_id)
        .where(
            JobQueue.id == job_id,
            JobQueue.job_type == "crawl",
            Site.workspace_id == workspace_id,
        )
    )
    if for_update:
        query = query.with_for_update()
    job = await db.scalar(query)
    if not job:
        raise CrawlJobServiceError("Crawl job not found", 404)
    return job


async def request_crawl_cancellation(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
) -> JobQueue:
    job = await get_crawl_job(
        db,
        workspace_id=workspace_id,
        job_id=job_id,
        for_update=True,
    )
    if job.status in TERMINAL_CRAWL_STATUSES:
        return job
    job.cancellation_requested = True
    if job.status in {"queued", "retry_wait"}:
        now = _now()
        job.status = "cancelled"
        job.completed_at = now
        job.lease_owner = None
        job.lease_expires_at = None
        site = await db.get(Site, job.site_id)
        if site:
            site.status = "crawl_cancelled"
    await db.commit()
    await db.refresh(job)
    return job


async def resume_crawl_job(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
) -> JobQueue:
    initial_job = await get_crawl_job(
        db,
        workspace_id=workspace_id,
        job_id=job_id,
        for_update=False,
    )
    workspace = await db.scalar(
        select(Workspace).where(Workspace.id == workspace_id).with_for_update()
    )
    if not workspace:
        raise CrawlJobServiceError("Crawl workspace not found", 404)
    site = await db.scalar(select(Site).where(Site.id == initial_job.site_id).with_for_update())
    job = await db.scalar(
        select(JobQueue)
        .where(JobQueue.id == job_id, JobQueue.job_type == "crawl")
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not job:
        raise CrawlJobServiceError("Crawl job not found", 404)
    if job.status not in {"failed", "cancelled"}:
        raise CrawlJobServiceError("Only failed or cancelled crawls can be resumed", 409)
    if not site or site.workspace_id != workspace_id:
        raise CrawlJobServiceError("Crawl site is outside this workspace", 404)
    another_active = await db.scalar(
        select(JobQueue)
        .where(
            JobQueue.site_id == job.site_id,
            JobQueue.id != job.id,
            JobQueue.job_type == "crawl",
            JobQueue.status.in_(ACTIVE_CRAWL_STATUSES),
        )
        .limit(1)
    )
    if another_active:
        raise CrawlJobServiceError(
            f"Another crawl is already active for this site ({another_active.id})",
            409,
        )
    subscription, _, current = await assert_usage_quota(
        db,
        workspace_id=workspace_id,
        metric="monthly_crawl_pages",
        requested=1,
    )
    active_reservations = list(
        (
            await db.execute(
                select(JobQueue)
                .join(Site, Site.id == JobQueue.site_id)
                .where(
                    Site.workspace_id == workspace_id,
                    JobQueue.job_type == "crawl",
                    JobQueue.status.in_(ACTIVE_CRAWL_STATUSES),
                )
            )
        ).scalars().all()
    )
    reserved = sum(
        max(0, int((reserved_job.payload or {}).get("max_pages") or 0))
        for reserved_job in active_reservations
    )
    limit = int(effective_entitlements(subscription)["monthly_crawl_pages"])
    available = max(0, limit - current - reserved)
    previously_crawled = int((job.result or {}).get("pages_crawled") or 0)
    if available < max(1, previously_crawled):
        raise QuotaExceededError(
            "monthly_crawl_pages",
            limit,
            current + reserved,
            max(1, previously_crawled),
        )
    resumed_max_pages = min(
        max(1, int((job.payload or {}).get("max_pages") or 100)),
        available,
    )
    now = _now()
    job.status = "queued"
    job.cancellation_requested = False
    job.run_after = now
    job.completed_at = None
    job.error_code = None
    job.error_message = None
    job.lease_owner = None
    job.lease_expires_at = None
    job.payload = {
        **(job.payload or {}),
        "max_pages": resumed_max_pages,
        "retry_cycle_started_at_attempt": job.attempt_count,
    }
    # A deliberate resume is a new retry budget while preserving attempt history.
    job.max_attempts = max(job.max_attempts, job.attempt_count + settings.crawl_job_max_attempts)
    await db.execute(
        update(CrawlFrontier)
        .where(
            CrawlFrontier.job_id == job.id,
            CrawlFrontier.status.in_(["fetching", "failed", "blocked"]),
        )
        .values(status="queued", last_error=None, completed_at=None)
    )
    site.status = "crawl_queued"
    linked_runs = list(
        (
            await db.execute(
                select(AgentRun).where(
                    AgentRun.site_id == job.site_id,
                    AgentRun.status == "failed",
                )
            )
        ).scalars().all()
    )
    for run in linked_runs:
        if str((run.meta or {}).get("crawl_job_id") or "") == str(job.id):
            run.status = "crawling"
            run.error = None
            run.summary = "Crawl resumed; analysis will continue after it succeeds."
            run.completed_at = None
            run.meta = {**(run.meta or {}), "phase": "crawl"}
    await db.commit()
    await db.refresh(job)
    await _signal_job(job.id)
    return job


async def recover_expired_crawl_leases(db: AsyncSession) -> int:
    now = _now()
    jobs = list(
        (
            await db.execute(
                select(JobQueue)
                .where(
                    JobQueue.job_type == "crawl",
                    JobQueue.status == "running",
                    JobQueue.lease_expires_at.is_not(None),
                    JobQueue.lease_expires_at < now,
                )
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
    )
    for job in jobs:
        site = await db.get(Site, job.site_id)
        await db.execute(
            update(CrawlFrontier)
            .where(CrawlFrontier.job_id == job.id, CrawlFrontier.status == "fetching")
            .values(status="queued")
        )
        attempt = await db.scalar(
            select(CrawlAttempt)
            .where(CrawlAttempt.job_id == job.id, CrawlAttempt.status == "running")
            .order_by(CrawlAttempt.attempt_number.desc())
            .limit(1)
        )
        if attempt:
            attempt.status = "failed"
            attempt.error_code = "lease_expired"
            attempt.error_message = "Worker heartbeat expired"
            attempt.completed_at = now
        job.lease_owner = None
        job.lease_expires_at = None
        job.heartbeat_at = None
        if job.cancellation_requested:
            job.status = "cancelled"
            job.completed_at = now
            if site:
                site.status = "crawl_cancelled"
        elif job.attempt_count >= job.max_attempts:
            job.status = "failed"
            job.error_code = "lease_expired"
            job.error_message = "Crawl lease expired after the final attempt"
            job.completed_at = now
            if site:
                site.status = "crawl_failed"
        else:
            job.status = "retry_wait"
            job.run_after = now
            if site:
                site.status = "crawl_queued"
    if jobs:
        await db.commit()
    return len(jobs)


async def claim_next_crawl_job(
    db: AsyncSession,
    *,
    worker_id: str,
    preferred_job_id: uuid.UUID | None = None,
) -> JobQueue | None:
    now = _now()
    query = select(JobQueue).where(
        JobQueue.job_type == "crawl",
        JobQueue.status.in_(["queued", "retry_wait"]),
        JobQueue.run_after <= now,
        JobQueue.cancellation_requested.is_(False),
    )
    if preferred_job_id:
        query = query.where(JobQueue.id == preferred_job_id)
    query = (
        query.order_by(JobQueue.priority.desc(), JobQueue.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = await db.scalar(query)
    if not job and preferred_job_id:
        return await claim_next_crawl_job(db, worker_id=worker_id)
    if not job:
        return None
    job.status = "running"
    job.lease_owner = worker_id
    job.lease_expires_at = now + timedelta(seconds=settings.crawl_job_lease_seconds)
    job.heartbeat_at = now
    job.started_at = job.started_at or now
    await db.commit()
    await db.refresh(job)
    return job


async def _heartbeat(
    *,
    job_id: uuid.UUID,
    worker_id: str,
) -> bool:
    now = _now()
    async with async_session_factory() as heartbeat_db:
        row = (
            await heartbeat_db.execute(
                update(JobQueue)
                .where(
                    JobQueue.id == job_id,
                    JobQueue.status == "running",
                    JobQueue.lease_owner == worker_id,
                    JobQueue.lease_expires_at.is_not(None),
                    JobQueue.lease_expires_at >= now,
                )
                .values(
                    heartbeat_at=now,
                    lease_expires_at=now + timedelta(seconds=settings.crawl_job_lease_seconds),
                )
                .returning(JobQueue.cancellation_requested)
            )
        ).first()
        if row is None:
            await heartbeat_db.rollback()
            raise CrawlLeaseLost("Crawl worker no longer owns a valid job lease")
        await heartbeat_db.commit()
        return bool(row[0])


async def _heartbeat_loop(
    *,
    job_id: uuid.UUID,
    worker_id: str,
    stop: asyncio.Event,
    cancellation_seen: asyncio.Event,
    lease_lost: asyncio.Event,
) -> None:
    interval = max(1.0, settings.crawl_job_lease_seconds / 3)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            pass
        try:
            if await _heartbeat(job_id=job_id, worker_id=worker_id):
                cancellation_seen.set()
        except CrawlLeaseLost:
            lease_lost.set()
            return
        except Exception:
            logger.exception("Crawl heartbeat failed for job %s", job_id)
            lease_lost.set()
            return


async def _analysis_heartbeat(run_id: uuid.UUID, lease_owner: str) -> bool:
    async with async_session_factory() as db:
        run = await db.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
        if (
            not run
            or run.status != "running"
            or (run.meta or {}).get("analysis_lease_owner") != lease_owner
        ):
            return False
        run.meta = {
            **(run.meta or {}),
            "analysis_lease_expires_at": (
                _now() + timedelta(seconds=max(settings.crawl_job_lease_seconds, 900))
            ).isoformat(),
        }
        await db.commit()
        return True


async def _analysis_heartbeat_loop(
    run_id: uuid.UUID,
    lease_owner: str,
    stop: asyncio.Event,
) -> None:
    interval = max(5.0, max(settings.crawl_job_lease_seconds, 900) / 3)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            pass
        try:
            if not await _analysis_heartbeat(run_id, lease_owner):
                return
        except Exception:
            logger.exception("Agent analysis heartbeat failed for run %s", run_id)


async def process_crawl_job(
    db: AsyncSession,
    *,
    job_id: uuid.UUID,
    worker_id: str,
) -> JobQueue:
    job = await db.scalar(select(JobQueue).where(JobQueue.id == job_id).with_for_update())
    if not job:
        raise CrawlJobServiceError("Crawl job not found", 404)
    if job.status != "running" or job.lease_owner != worker_id:
        raise CrawlJobServiceError("Crawl job is not leased by this worker", 409)
    site = await db.get(Site, job.site_id)
    if not site:
        raise CrawlJobServiceError("Crawl site not found", 404)
    workspace_id = _job_workspace_id(job)
    if site.workspace_id != workspace_id:
        raise CrawlJobServiceError("Crawl job tenant boundary is invalid", 409)

    now = _now()
    job.attempt_count += 1
    job.error_code = None
    job.error_message = None
    site.status = "crawling"
    attempt = CrawlAttempt(
        job_id=job.id,
        attempt_number=job.attempt_count,
        worker_id=worker_id,
        status="running",
    )
    db.add(attempt)
    await db.commit()
    await db.refresh(attempt)

    heartbeat_stop = asyncio.Event()
    cancellation_seen = asyncio.Event()
    lease_lost = asyncio.Event()

    async def control() -> bool:
        if lease_lost.is_set():
            raise CrawlLeaseLost("Crawl worker lost its job lease")
        if cancellation_seen.is_set():
            return True
        cancelled = await _heartbeat(job_id=job_id, worker_id=worker_id)
        if cancelled:
            cancellation_seen.set()
        return cancelled

    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(
            job_id=job_id,
            worker_id=worker_id,
            stop=heartbeat_stop,
            cancellation_seen=cancellation_seen,
            lease_lost=lease_lost,
        )
    )

    try:
        if await control():
            raise InterruptedError("Crawl cancellation requested")
        snapshot = await run_crawl(
            db,
            site.id,
            site.domain,
            max_pages=int((job.payload or {}).get("max_pages") or 100),
            job_id=job.id,
            control=control,
        )
        if await control():
            raise InterruptedError("Crawl cancellation requested")
        heartbeat_stop.set()
        await heartbeat_task

        # Fence terminal state and metering in one transaction. Recovery or a
        # new claim cannot pass this row lock, and an already-expired owner is
        # never allowed to complete or charge the job.
        now = _now()
        job = await db.scalar(
            select(JobQueue)
            .where(JobQueue.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        site = await db.get(Site, site.id)
        if (
            not job
            or job.status != "running"
            or job.lease_owner != worker_id
            or not job.lease_expires_at
            or job.lease_expires_at < now
        ):
            raise CrawlLeaseLost("Crawl worker lost its lease before finalization")
        if not site:
            raise CrawlJobServiceError("Crawl state disappeared during execution", 409)
        attempt = await db.scalar(
            select(CrawlAttempt)
            .where(
                CrawlAttempt.job_id == job.id,
                CrawlAttempt.attempt_number == job.attempt_count,
            )
            .limit(1)
        )
        if not attempt or attempt.worker_id != worker_id or attempt.status != "running":
            raise CrawlLeaseLost("Crawl attempt fencing token is no longer current")

        result = {
            "adapter": "first_party",
            "snapshot_id": str(snapshot.id),
            "pages_discovered": int(snapshot.pages_discovered or 0),
            "pages_crawled": int(snapshot.pages_crawled or 0),
            "errors": int(snapshot.errors or 0),
            "details": snapshot.extracted_data or {},
        }
        job.result = result
        job.lease_owner = None
        job.lease_expires_at = None
        job.heartbeat_at = _now()
        attempt.completed_at = _now()

        if snapshot.status == "cancelled" or job.cancellation_requested:
            job.status = "cancelled"
            job.completed_at = _now()
            attempt.status = "cancelled"
            site.status = "crawl_cancelled"
        elif snapshot.status == "completed" and int(snapshot.pages_crawled or 0) > 0:
            workspace = await db.scalar(
                select(Workspace).where(Workspace.id == workspace_id).with_for_update()
            )
            if not workspace:
                raise CrawlJobServiceError("Crawl workspace disappeared during execution", 409)
            job.status = "completed"
            job.completed_at = _now()
            attempt.status = "completed"
            site.status = "ready"
            await record_usage(
                db,
                workspace_id=workspace_id,
                site_id=site.id,
                metric="monthly_crawl_pages",
                quantity=int(snapshot.pages_crawled or 0),
                purpose="site_crawl",
                details={"adapter": "first_party", "snapshot_id": str(snapshot.id), "job_id": str(job.id)},
                commit=False,
                enforce_quota=False,
            )
        else:
            error = str((snapshot.extracted_data or {}).get("error") or "Crawl produced no pages")
            raise RuntimeError(error)
        await db.commit()
        await db.refresh(job)
        return job
    except CrawlLeaseLost:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        job = await db.scalar(
            select(JobQueue)
            .where(JobQueue.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            not job
            or job.status != "running"
            or job.lease_owner != worker_id
            or not job.lease_expires_at
            or job.lease_expires_at < _now()
        ):
            raise CrawlLeaseLost("Crawl worker lost its lease during failure handling") from exc
        site = await db.get(Site, job.site_id) if job else None
        attempt = await db.scalar(
            select(CrawlAttempt)
            .where(CrawlAttempt.job_id == job.id, CrawlAttempt.attempt_number == job.attempt_count)
            .limit(1)
        )
        error_code = "cancelled" if isinstance(exc, InterruptedError) else "crawl_failed"
        error_message = str(exc)[:2000]
        if attempt:
            attempt.status = "cancelled" if error_code == "cancelled" else "failed"
            attempt.error_code = error_code
            attempt.error_message = error_message
            attempt.completed_at = _now()
        job.error_code = error_code
        job.error_message = error_message
        job.result = {**(job.result or {}), "adapter": "first_party", "error": error_message}
        job.lease_owner = None
        job.lease_expires_at = None
        await db.execute(
            update(CrawlFrontier)
            .where(CrawlFrontier.job_id == job.id, CrawlFrontier.status == "fetching")
            .values(status="queued")
        )
        if job.cancellation_requested or error_code == "cancelled":
            job.status = "cancelled"
            job.completed_at = _now()
            if site:
                site.status = "crawl_cancelled"
        elif job.attempt_count < job.max_attempts:
            cycle_start = int((job.payload or {}).get("retry_cycle_started_at_attempt") or 0)
            retry_ordinal = max(0, min(job.attempt_count - cycle_start - 1, 10))
            delay = settings.crawl_retry_base_seconds * (2 ** retry_ordinal)
            job.status = "retry_wait"
            job.run_after = _now() + timedelta(seconds=delay)
            if site:
                site.status = "crawl_queued"
        else:
            job.status = "failed"
            job.completed_at = _now()
            if site:
                site.status = "crawl_failed"
        await db.commit()
        await db.refresh(job)
        if job.status == "retry_wait":
            await _signal_job(job.id)
        return job
    finally:
        heartbeat_stop.set()
        if not heartbeat_task.done():
            await heartbeat_task


async def reconcile_agent_runs_waiting_for_crawl(limit: int = 5) -> int:
    continued = 0
    ready_for_analysis: list[tuple[uuid.UUID, uuid.UUID, str]] = []
    async with async_session_factory() as db:
        runs = list(
            (
                await db.execute(
                    select(AgentRun)
                    .where(AgentRun.status.in_(["crawling", "running"]))
                    .order_by(AgentRun.started_at.asc())
                    .with_for_update(skip_locked=True)
                    .limit(limit)
                )
            ).scalars().all()
        )
        for run in runs:
            meta = run.meta or {}
            if run.status == "running" and meta.get("phase") == "analysis":
                raw_expiry = meta.get("analysis_lease_expires_at")
                try:
                    lease_expiry = datetime.fromisoformat(str(raw_expiry))
                    if lease_expiry.tzinfo is None:
                        lease_expiry = lease_expiry.replace(tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    lease_expiry = datetime.min.replace(tzinfo=timezone.utc)
                if lease_expiry > _now():
                    continue
            raw_job_id = (run.meta or {}).get("crawl_job_id")
            try:
                crawl_job_id = uuid.UUID(str(raw_job_id))
            except (TypeError, ValueError):
                continue
            job = await db.get(JobQueue, crawl_job_id)
            if not job or job.status not in TERMINAL_CRAWL_STATUSES:
                continue
            if job.job_type != "crawl" or job.site_id != run.site_id:
                run.status = "failed"
                run.error = "The linked crawl job does not belong to this agent run."
                run.summary = run.error
                run.completed_at = _now()
                continued += 1
                continue
            if job.status != "completed":
                run.status = "failed"
                run.error = job.error_message or "The crawl failed before analysis."
                run.summary = run.error
                run.completed_at = _now()
                continued += 1
                continue
            page_count = int(
                await db.scalar(select(func.count(Page.id)).where(Page.site_id == run.site_id)) or 0
            )
            if page_count < 1:
                run.status = "failed"
                run.error = "The crawl completed without any stored pages."
                run.summary = run.error
                run.completed_at = _now()
                continued += 1
                continue
            analysis_lease_owner = f"{WORKER_ID}:analysis:{uuid.uuid4().hex[:12]}"
            run.status = "running"
            run.summary = f"Crawl completed with {page_count} pages. Starting analysis."
            run.meta = {
                **(run.meta or {}),
                "phase": "analysis",
                "analysis_lease_owner": analysis_lease_owner,
                "analysis_lease_expires_at": (
                    _now() + timedelta(seconds=max(settings.crawl_job_lease_seconds, 900))
                ).isoformat(),
            }
            ready_for_analysis.append((run.site_id, run.id, analysis_lease_owner))
            continued += 1
        if continued:
            await db.commit()
    for site_id, run_id, lease_owner in ready_for_analysis:
        heartbeat_stop = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            _analysis_heartbeat_loop(run_id, lease_owner, heartbeat_stop)
        )
        try:
            await run_agent_graph(site_id, run_id, analysis_lease_owner=lease_owner)
        finally:
            heartbeat_stop.set()
            if not heartbeat_task.done():
                await heartbeat_task
    return continued


async def _fail_claimed_job(job_id: uuid.UUID, worker_id: str, exc: Exception) -> None:
    async with async_session_factory() as db:
        job = await db.scalar(select(JobQueue).where(JobQueue.id == job_id).with_for_update())
        if not job or job.status != "running" or job.lease_owner != worker_id:
            return
        job.status = "failed"
        job.error_code = "worker_error"
        job.error_message = str(exc)[:2000]
        job.completed_at = _now()
        job.lease_owner = None
        job.lease_expires_at = None
        site = await db.get(Site, job.site_id)
        if site:
            site.status = "crawl_failed"
        await db.commit()


async def run_crawl_worker_tick(preferred_job_id: uuid.UUID | None = None) -> int:
    processed = 0
    async with async_session_factory() as db:
        await recover_expired_crawl_leases(db)
    batch_size = 1 if preferred_job_id else settings.crawl_worker_batch_size
    for index in range(batch_size):
        preferred = preferred_job_id if index == 0 and preferred_job_id else await _pop_signal()
        lease_id = f"{WORKER_ID}:{uuid.uuid4().hex[:12]}"
        async with async_session_factory() as db:
            job = await claim_next_crawl_job(db, worker_id=lease_id, preferred_job_id=preferred)
        if not job:
            break
        async with async_session_factory() as db:
            try:
                await process_crawl_job(db, job_id=job.id, worker_id=lease_id)
            except CrawlLeaseLost:
                logger.warning("Crawl worker lost lease for job %s", job.id)
            except Exception as exc:
                logger.exception("Crawl worker failed job %s", job.id)
                await db.rollback()
                await _fail_claimed_job(job.id, lease_id, exc)
        processed += 1
        if preferred_job_id:
            break
    await reconcile_agent_runs_waiting_for_crawl()
    return processed
