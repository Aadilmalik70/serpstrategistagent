from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

import httpx
from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_factory
from app.models.google_data_connection import GoogleDataConnection
from app.models.job_queue import JobQueue
from app.models.page import Page
from app.models.search_performance import (
    SearchAnalyticsMetric,
    SearchOpportunity,
    UrlInspectionAttempt,
    UrlInspectionResult,
)
from app.models.site import Site
from app.services.google_data_service import _access_token
from app.services.search_performance_service import (
    ACTIVE_STATUSES,
    SearchPerformanceError,
    _host,
    _now,
    _property_matches_site,
    _reconcile_opportunity_actions,
)


logger = logging.getLogger(__name__)
settings = get_settings()
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:url-inspection:{uuid.uuid4().hex[:8]}"
URL_INSPECTION_OPPORTUNITY_TYPES = {
    "indexation_blocked",
    "not_indexed",
    "canonical_mismatch",
}


class UrlInspectionError(SearchPerformanceError):
    pass


def _canonical_inspection_url(site_domain: str, value: str) -> str:
    raw = value.strip()
    if not raw:
        raise UrlInspectionError("Inspection URLs cannot be empty", 422, code="invalid_inspection_url")
    site_value = site_domain if "://" in site_domain else f"https://{site_domain}"
    site = urlsplit(site_value)
    parsed = urlsplit(raw)
    if not parsed.scheme and not parsed.netloc:
        path = parsed.path if parsed.path.startswith("/") else f"/{parsed.path}"
        parsed = urlsplit(urlunsplit((site.scheme or "https", site.netloc, path, parsed.query, "")))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UrlInspectionError("Inspection URLs must be absolute HTTP or HTTPS URLs", 422, code="invalid_inspection_url")
    if parsed.username or parsed.password:
        raise UrlInspectionError("Inspection URLs cannot contain embedded credentials", 422, code="invalid_inspection_url")
    if _host(parsed.hostname) != _host(site_domain):
        raise UrlInspectionError("Inspection URLs must belong to the selected site", 422, code="invalid_inspection_scope")
    normalized = urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))
    if len(normalized) > 2048:
        raise UrlInspectionError("Inspection URLs cannot exceed 2048 characters", 422, code="invalid_inspection_url")
    return normalized


async def _candidate_urls(db: AsyncSession, *, site: Site) -> list[str]:
    limit = settings.url_inspection_max_urls_per_job
    values: list[str] = []
    search_pages = list(
        (
            await db.execute(
                select(SearchAnalyticsMetric.page_url)
                .where(SearchAnalyticsMetric.site_id == site.id)
                .group_by(SearchAnalyticsMetric.page_url)
                .order_by(func.sum(SearchAnalyticsMetric.impressions).desc())
                .limit(limit * 2)
            )
        ).scalars().all()
    )
    values.extend(search_pages)
    crawled_pages = list(
        (
            await db.execute(
                select(Page.path)
                .where(Page.site_id == site.id, Page.status_code == 200)
                .order_by(Page.last_crawled_at.desc().nullslast(), Page.path.asc())
                .limit(limit * 2)
            )
        ).scalars().all()
    )
    values.extend(crawled_pages)
    values.append("/")
    selected: list[str] = []
    seen: set[str] = set()
    for value in values:
        try:
            url = _canonical_inspection_url(site.domain, str(value))
        except UrlInspectionError:
            continue
        key = hashlib.sha256(url.encode()).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        selected.append(url)
        if len(selected) >= limit:
            break
    return selected


async def _signal_job(job_id: uuid.UUID) -> None:
    if not settings.redis_url:
        return
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis.rpush(settings.url_inspection_queue_key, str(job_id))
        await redis.ltrim(settings.url_inspection_queue_key, -1000, -1)
        await redis.expire(settings.url_inspection_queue_key, 86400)
    except Exception as exc:
        logger.warning("URL Inspection Redis signal failed: %s", type(exc).__name__)
    finally:
        await redis.aclose()


async def enqueue_url_inspection(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    site_id: uuid.UUID,
    urls: list[str] | None = None,
    source: str = "operator",
) -> tuple[JobQueue, bool]:
    site = await db.scalar(select(Site).where(Site.id == site_id).with_for_update())
    if not site or site.workspace_id != workspace_id:
        raise UrlInspectionError("Site not found in this workspace", 404)
    connection = await db.scalar(
        select(GoogleDataConnection).where(GoogleDataConnection.workspace_id == workspace_id)
    )
    if not connection or connection.status != "configured" or not connection.gsc_property:
        raise UrlInspectionError("Configure a Search Console property before inspecting URLs", 409)
    if not _property_matches_site(connection.gsc_property, site.domain):
        raise UrlInspectionError("The selected Search Console property does not cover this site", 409)
    active = await db.scalar(
        select(JobQueue).where(
            JobQueue.site_id == site_id,
            JobQueue.job_type == "gsc_url_inspection",
            JobQueue.status.in_(ACTIVE_STATUSES),
        ).limit(1)
    )
    if active:
        return active, True
    if urls:
        if len(urls) > settings.url_inspection_max_urls_per_job:
            raise UrlInspectionError(
                f"URL Inspection is limited to {settings.url_inspection_max_urls_per_job} URLs per job",
                422,
                code="url_inspection_url_cap",
            )
        selected = list(dict.fromkeys(_canonical_inspection_url(site.domain, value) for value in urls))
    else:
        selected = await _candidate_urls(db, site=site)
    if not selected:
        raise UrlInspectionError("No eligible site URLs are available for inspection", 409)
    if settings.url_inspection_min_interval_minutes:
        recent = await db.scalar(
            select(JobQueue)
            .where(
                JobQueue.site_id == site_id,
                JobQueue.job_type == "gsc_url_inspection",
                JobQueue.created_at >= _now() - timedelta(minutes=settings.url_inspection_min_interval_minutes),
            )
            .order_by(JobQueue.created_at.desc())
            .limit(1)
        )
        if recent:
            recent_urls = [str(value) for value in (recent.payload or {}).get("urls", [])]
            # An empty request means "use the best candidates". During the
            # cooldown, return the most recent completed inspection instead of
            # deriving a new candidate list and then rejecting it as different.
            if recent.status == "completed" and (not urls or recent_urls == selected):
                return recent, True
            retry_at = recent.created_at + timedelta(minutes=settings.url_inspection_min_interval_minutes)
            retry_after = max(1, int((retry_at - _now()).total_seconds()) + 1)
            raise UrlInspectionError(
                "A URL Inspection attempt already reserved this site; retry after the cooldown window",
                429,
                code="url_inspection_cooldown",
                retry_after_seconds=retry_after,
            )
    job = JobQueue(
        site_id=site_id,
        job_type="gsc_url_inspection",
        status="queued",
        max_attempts=settings.url_inspection_job_max_attempts,
        run_after=_now(),
        payload={
            "workspace_id": str(workspace_id),
            "connection_id": str(connection.id),
            "gsc_property": connection.gsc_property,
            "source": source,
            "urls": selected,
        },
        result={"processed": 0, "total": len(selected), "opportunities": 0},
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    await _signal_job(job.id)
    return job, False


async def _inspect_url(
    client: httpx.AsyncClient,
    *,
    token: str,
    property_id: str,
    inspection_url: str,
) -> dict:
    response = await client.post(
        settings.google_search_console_inspection_api_url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"inspectionUrl": inspection_url, "siteUrl": property_id, "languageCode": "en-US"},
    )
    if response.status_code >= 400:
        retryable = response.status_code == 429 or response.status_code >= 500
        raise UrlInspectionError(
            f"Search Console URL Inspection returned HTTP {response.status_code}",
            502 if retryable else response.status_code,
            code="url_inspection_provider_unavailable" if retryable else "url_inspection_rejected",
            retryable=retryable,
        )
    result = response.json().get("inspectionResult")
    if not isinstance(result, dict):
        raise UrlInspectionError(
            "Search Console URL Inspection returned an invalid response",
            502,
            code="invalid_url_inspection_response",
            retryable=True,
        )
    return result


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


async def _persist_result(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    site_id: uuid.UUID,
    inspection_url: str,
    payload: dict,
) -> None:
    index = payload.get("indexStatusResult") or {}
    if not isinstance(index, dict):
        index = {}
    now = _now()
    values = {
        "workspace_id": workspace_id,
        "site_id": site_id,
        "inspection_url": inspection_url,
        "url_hash": hashlib.sha256(inspection_url.encode()).hexdigest(),
        "verdict": str(index.get("verdict") or "VERDICT_UNSPECIFIED")[:64],
        "coverage_state": str(index.get("coverageState"))[:255] if index.get("coverageState") else None,
        "robots_txt_state": str(index.get("robotsTxtState"))[:64] if index.get("robotsTxtState") else None,
        "indexing_state": str(index.get("indexingState"))[:64] if index.get("indexingState") else None,
        "page_fetch_state": str(index.get("pageFetchState"))[:64] if index.get("pageFetchState") else None,
        "crawled_as": str(index.get("crawledAs"))[:64] if index.get("crawledAs") else None,
        "google_canonical": str(index.get("googleCanonical"))[:2048] if index.get("googleCanonical") else None,
        "user_canonical": str(index.get("userCanonical"))[:2048] if index.get("userCanonical") else None,
        "last_crawl_time": _parse_time(index.get("lastCrawlTime")),
        "referring_urls": [
            str(value)[:2048]
            for value in (
                index.get("referringUrls")
                if isinstance(index.get("referringUrls"), list)
                else []
            )[:100]
        ],
        "sitemap_urls": [
            str(value)[:2048]
            for value in (
                index.get("sitemap") if isinstance(index.get("sitemap"), list) else []
            )[:100]
        ],
        "raw_result": payload,
        "inspected_at": now,
        "updated_at": now,
    }
    await db.execute(
        insert(UrlInspectionResult)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_url_inspection_site_url",
            set_={key: value for key, value in values.items() if key not in {"workspace_id", "site_id", "url_hash"}},
        )
    )


def _inspection_candidates(result: UrlInspectionResult) -> list[tuple[str, str, int]]:
    candidates: list[tuple[str, str, int]] = []
    coverage = (result.coverage_state or "").lower()
    blocking = result.robots_txt_state == "DISALLOWED" or result.indexing_state in {
        "BLOCKED_BY_META_TAG",
        "BLOCKED_BY_HTTP_HEADER",
    } or result.page_fetch_state not in {
        None,
        "PAGE_FETCH_STATE_UNSPECIFIED",
        "SUCCESSFUL",
    }
    if blocking:
        candidates.append(("indexation_blocked", f"Remove the indexing blocker for {result.inspection_url}", 90))
    elif result.verdict in {"FAIL", "NEUTRAL"} or "not indexed" in coverage or "excluded" in coverage:
        candidates.append(("not_indexed", f"Investigate why Google has not indexed {result.inspection_url}", 82))
    if (
        result.google_canonical
        and result.user_canonical
        and result.google_canonical.rstrip("/") != result.user_canonical.rstrip("/")
    ):
        candidates.append(("canonical_mismatch", f"Resolve Google's canonical mismatch for {result.inspection_url}", 75))
    return candidates


async def reconcile_url_inspection_opportunities(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    site_id: uuid.UUID,
) -> list[SearchOpportunity]:
    results = list(
        (
            await db.execute(
                select(UrlInspectionResult).where(
                    UrlInspectionResult.workspace_id == workspace_id,
                    UrlInspectionResult.site_id == site_id,
                )
            )
        ).scalars().all()
    )
    existing = list(
        (
            await db.execute(
                select(SearchOpportunity).where(
                    SearchOpportunity.workspace_id == workspace_id,
                    SearchOpportunity.site_id == site_id,
                    SearchOpportunity.opportunity_type.in_(URL_INSPECTION_OPPORTUNITY_TYPES),
                )
            )
        ).scalars().all()
    )
    by_key = {item.opportunity_key: item for item in existing}
    now = _now()
    seen: set[str] = set()
    active: list[SearchOpportunity] = []
    for result in results:
        for opportunity_type, title, priority in _inspection_candidates(result):
            key = hashlib.sha256(f"{opportunity_type}|{result.inspection_url}".encode()).hexdigest()
            seen.add(key)
            record = by_key.get(key)
            if record is None:
                record = SearchOpportunity(
                    workspace_id=workspace_id,
                    site_id=site_id,
                    opportunity_key=key,
                    opportunity_type=opportunity_type,
                    first_detected_at=now,
                )
                db.add(record)
            record.status = "active"
            record.title = title[:500]
            record.query = None
            record.page_url = result.inspection_url
            record.priority_score = priority
            record.confidence_score = 95 if result.verdict != "VERDICT_UNSPECIFIED" else 60
            record.metrics = {
                "verdict": result.verdict,
                "coverage_state": result.coverage_state,
                "robots_txt_state": result.robots_txt_state,
                "indexing_state": result.indexing_state,
                "page_fetch_state": result.page_fetch_state,
            }
            record.evidence = [
                {
                    "source": "gsc_url_inspection",
                    "inspection_result_id": str(result.id),
                    "inspected_at": result.inspected_at.isoformat(),
                    "google_canonical": result.google_canonical,
                    "user_canonical": result.user_canonical,
                }
            ]
            record.last_detected_at = now
            record.resolved_at = None
            active.append(record)
    resolved: list[SearchOpportunity] = []
    for record in existing:
        if record.status == "active" and record.opportunity_key not in seen:
            record.status = "resolved"
            record.resolved_at = now
            resolved.append(record)
    await db.flush()
    await _reconcile_opportunity_actions(
        db,
        workspace_id=workspace_id,
        site_id=site_id,
        opportunities=sorted(active, key=lambda item: (-item.priority_score, str(item.id)))[
            : settings.search_opportunity_action_limit
        ],
        resolved=resolved,
    )
    return active


async def _claim_job(db: AsyncSession) -> JobQueue | None:
    now = _now()
    job = await db.scalar(
        select(JobQueue)
        .where(
            JobQueue.job_type == "gsc_url_inspection",
            JobQueue.status.in_(["queued", "retry_wait"]),
            JobQueue.run_after <= now,
        )
        .order_by(JobQueue.priority.desc(), JobQueue.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not job:
        return None
    job.status = "running"
    job.lease_owner = WORKER_ID
    job.lease_expires_at = now + timedelta(seconds=settings.url_inspection_job_lease_seconds)
    job.started_at = job.started_at or now
    job.attempt_count += 1
    db.add(UrlInspectionAttempt(job_id=job.id, attempt_number=job.attempt_count, worker_id=WORKER_ID))
    await db.commit()
    await db.refresh(job)
    return job


async def _process_job(db: AsyncSession, job_id: uuid.UUID) -> JobQueue:
    job = await db.get(JobQueue, job_id)
    if not job or job.status != "running" or job.lease_owner != WORKER_ID:
        raise UrlInspectionError("URL Inspection job lease is unavailable", 409)
    payload = job.payload or {}
    try:
        workspace_id = uuid.UUID(str(payload["workspace_id"]))
        connection_id = uuid.UUID(str(payload["connection_id"]))
        urls = [str(value) for value in payload["urls"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise UrlInspectionError("URL Inspection job configuration is invalid", 409, code="invalid_job_configuration") from exc
    property_id = str(payload.get("gsc_property") or "")
    connection = await db.get(GoogleDataConnection, connection_id)
    site = await db.get(Site, job.site_id)
    if (
        not connection
        or connection.workspace_id != workspace_id
        or connection.status != "configured"
        or connection.gsc_property != property_id
        or not site
        or site.workspace_id != workspace_id
        or not _property_matches_site(property_id, site.domain)
    ):
        raise UrlInspectionError("Search Console connection is unavailable", 409, code="invalid_inspection_scope")
    token = await _access_token(db, connection)
    progress = dict(job.result or {})
    processed = min(int(progress.get("processed") or 0), len(urls))
    async with httpx.AsyncClient(timeout=settings.google_integration_timeout_seconds, follow_redirects=False) as client:
        for index in range(processed, len(urls)):
            inspection_url = _canonical_inspection_url(site.domain, urls[index])
            result = await _inspect_url(
                client,
                token=token,
                property_id=property_id,
                inspection_url=inspection_url,
            )
            await _persist_result(
                db,
                workspace_id=workspace_id,
                site_id=job.site_id,
                inspection_url=inspection_url,
                payload=result,
            )
            job = await db.scalar(select(JobQueue).where(JobQueue.id == job_id).with_for_update())
            if not job or job.status != "running" or job.lease_owner != WORKER_ID:
                raise UrlInspectionError("URL Inspection worker lost its lease", 409)
            job.result = {"processed": index + 1, "total": len(urls), "opportunities": 0}
            job.heartbeat_at = _now()
            await db.commit()

    job = await db.scalar(select(JobQueue).where(JobQueue.id == job_id).with_for_update())
    if not job or job.status != "running" or job.lease_owner != WORKER_ID:
        raise UrlInspectionError("URL Inspection worker lost its lease", 409)
    opportunities = await reconcile_url_inspection_opportunities(
        db,
        workspace_id=workspace_id,
        site_id=job.site_id,
    )
    result = {"processed": len(urls), "total": len(urls), "opportunities": len(opportunities)}
    job.status = "completed"
    job.result = result
    job.completed_at = _now()
    job.lease_owner = None
    job.lease_expires_at = None
    attempt = await db.scalar(
        select(UrlInspectionAttempt).where(
            UrlInspectionAttempt.job_id == job.id,
            UrlInspectionAttempt.attempt_number == job.attempt_count,
        )
    )
    if attempt:
        attempt.status = "completed"
        attempt.result = result
        attempt.completed_at = _now()
    await db.commit()
    await db.refresh(job)
    return job


async def recover_expired_url_inspection_leases(db: AsyncSession) -> int:
    now = _now()
    jobs = list(
        (
            await db.execute(
                select(JobQueue)
                .where(
                    JobQueue.job_type == "gsc_url_inspection",
                    JobQueue.status == "running",
                    JobQueue.lease_expires_at < now,
                )
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
    )
    for job in jobs:
        job.status = "retry_wait" if job.attempt_count < job.max_attempts else "failed"
        job.run_after = now
        job.error_code = "lease_expired"
        job.error_message = "URL Inspection worker lease expired"
        job.lease_owner = None
        job.lease_expires_at = None
        if job.status == "failed":
            job.completed_at = now
        attempt = await db.scalar(
            select(UrlInspectionAttempt).where(
                UrlInspectionAttempt.job_id == job.id,
                UrlInspectionAttempt.attempt_number == job.attempt_count,
            )
        )
        if attempt and attempt.status == "running":
            attempt.status = "failed"
            attempt.error_code = "lease_expired"
            attempt.error_message = job.error_message
            attempt.completed_at = now
    if jobs:
        await db.commit()
    return len(jobs)


async def _heartbeat(job_id: uuid.UUID, stop: asyncio.Event) -> None:
    interval = max(1.0, settings.url_inspection_job_lease_seconds / 3)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            break
        except TimeoutError:
            pass
        try:
            async with async_session_factory() as db:
                updated = await db.execute(
                    update(JobQueue)
                    .where(
                        JobQueue.id == job_id,
                        JobQueue.job_type == "gsc_url_inspection",
                        JobQueue.status == "running",
                        JobQueue.lease_owner == WORKER_ID,
                    )
                    .values(
                        heartbeat_at=_now(),
                        lease_expires_at=_now() + timedelta(seconds=settings.url_inspection_job_lease_seconds),
                    )
                )
                await db.commit()
                if updated.rowcount != 1:
                    break
        except Exception as exc:
            logger.warning("URL Inspection heartbeat failed for %s: %s", job_id, type(exc).__name__)


async def _consume_job_hints() -> None:
    if not settings.redis_url:
        return
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        for _ in range(max(10, settings.url_inspection_worker_batch_size * 10)):
            if await redis.lpop(settings.url_inspection_queue_key) is None:
                break
    except Exception as exc:
        logger.warning("URL Inspection Redis hint cleanup failed: %s", type(exc).__name__)
    finally:
        await redis.aclose()


async def run_url_inspection_worker_tick() -> int:
    await _consume_job_hints()
    async with async_session_factory() as db:
        await recover_expired_url_inspection_leases(db)
    processed = 0
    for _ in range(settings.url_inspection_worker_batch_size):
        async with async_session_factory() as db:
            job = await _claim_job(db)
        if not job:
            break
        stop = asyncio.Event()
        heartbeat = asyncio.create_task(_heartbeat(job.id, stop))
        try:
            async with async_session_factory() as db:
                await _process_job(db, job.id)
        except Exception as exc:
            logger.exception("URL Inspection job %s failed", job.id)
            async with async_session_factory() as db:
                failed = await db.scalar(select(JobQueue).where(JobQueue.id == job.id).with_for_update())
                if failed and failed.status == "running" and failed.lease_owner == WORKER_ID:
                    retryable = not isinstance(exc, SearchPerformanceError) or exc.retryable
                    failed.error_code = exc.code if isinstance(exc, SearchPerformanceError) else "url_inspection_failed"
                    failed.error_message = str(exc)[:2000]
                    failed.lease_owner = None
                    failed.lease_expires_at = None
                    if retryable and failed.attempt_count < failed.max_attempts:
                        failed.status = "retry_wait"
                        retry = min(failed.attempt_count - 1, 8)
                        failed.run_after = _now() + timedelta(
                            seconds=settings.url_inspection_retry_base_seconds * (2**retry)
                        )
                    else:
                        failed.status = "failed"
                        failed.completed_at = _now()
                    attempt = await db.scalar(
                        select(UrlInspectionAttempt).where(
                            UrlInspectionAttempt.job_id == failed.id,
                            UrlInspectionAttempt.attempt_number == failed.attempt_count,
                        )
                    )
                    if attempt:
                        attempt.status = "failed"
                        attempt.error_code = failed.error_code
                        attempt.error_message = failed.error_message
                        attempt.completed_at = _now()
                    await db.commit()
        finally:
            stop.set()
            await heartbeat
        processed += 1
    return processed
