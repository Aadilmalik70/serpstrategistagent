from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import socket
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from redis.asyncio import Redis
from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_factory
from app.models.google_data_connection import GoogleDataConnection
from app.models.job_queue import JobQueue
from app.models.operator_action import OperatorAction, OperatorActionEvent
from app.models.search_performance import (
    ActionMeasurement,
    SearchAnalyticsMetric,
    SearchOpportunity,
    SearchSyncAttempt,
)
from app.models.site import Site
from app.services.google_data_service import GoogleDataServiceError, _access_token
from app.services.execution_adapters import ExecutionAdapterUnavailable, get_execution_adapter


logger = logging.getLogger(__name__)
settings = get_settings()
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:gsc:{uuid.uuid4().hex[:8]}"
ACTIVE_STATUSES = {"queued", "running", "retry_wait"}
SEARCH_ANALYTICS_OPPORTUNITY_TYPES = {
    "low_ctr",
    "striking_distance",
    "traffic_decay",
    "cannibalization",
}


class SearchPerformanceError(ValueError):
    def __init__(
        self,
        message: str,
        status_code: int = 400,
        *,
        code: str = "search_performance_error",
        retryable: bool = False,
        retry_after_seconds: int | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class OpportunityCandidate:
    opportunity_type: str
    query: str | None
    page_url: str | None
    title: str
    priority_score: int
    confidence_score: int
    metrics: dict

    @property
    def key(self) -> str:
        value = f"{self.opportunity_type}|{self.query or ''}|{self.page_url or ''}"
        return hashlib.sha256(value.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _action_uses_mutating_adapter(action: OperatorAction) -> bool:
    target = action.execution_target or {}
    name = str(
        target.get("adapter") or target.get("provider") or target.get("type") or ""
    ).strip().lower()
    try:
        return bool(get_execution_adapter(name).mutation_enabled)
    except ExecutionAdapterUnavailable:
        return False


def _host(value: str) -> str:
    raw = value.strip()
    parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
    return (parsed.hostname or "").lower().rstrip(".").removeprefix("www.")


def _page_url_key(value: str) -> str:
    parsed = urlsplit(value.strip())
    host = (parsed.hostname or "").lower().rstrip(".").removeprefix("www.")
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    return f"{host}{path}{f'?{parsed.query}' if parsed.query else ''}"[:2100]


def _property_matches_site(property_id: str, site_domain: str) -> bool:
    site_host = _host(site_domain)
    if property_id.startswith("sc-domain:"):
        property_host = _host(property_id.split(":", 1)[1])
        return bool(site_host and property_host and (site_host == property_host or site_host.endswith(f".{property_host}")))
    parsed_property = urlsplit(property_id)
    if parsed_property.path not in {"", "/"} or parsed_property.query or parsed_property.fragment:
        return False
    return bool(site_host and _host(property_id) == site_host)


def _weighted_metrics(rows: list[SearchAnalyticsMetric]) -> dict[str, float]:
    clicks = sum(float(row.clicks or 0) for row in rows)
    impressions = sum(float(row.impressions or 0) for row in rows)
    weighted_position = sum(float(row.position or 0) * float(row.impressions or 0) for row in rows)
    return {
        "clicks": round(clicks, 3),
        "impressions": round(impressions, 3),
        "ctr": round(clicks / impressions, 6) if impressions else 0.0,
        "position": round(weighted_position / impressions, 3) if impressions else 0.0,
    }


def classify_action_outcome(baseline: dict, comparison: dict) -> tuple[str, dict, int]:
    before_impressions = float(baseline.get("impressions") or 0)
    after_impressions = float(comparison.get("impressions") or 0)
    if before_impressions < 20 or after_impressions < 20:
        return "insufficient_data", {}, 0

    before_clicks = float(baseline.get("clicks") or 0)
    after_clicks = float(comparison.get("clicks") or 0)
    before_ctr = float(baseline.get("ctr") or 0)
    after_ctr = float(comparison.get("ctr") or 0)
    clicks_change = (after_clicks - before_clicks) / max(before_clicks, 1.0)
    ctr_change = (after_ctr - before_ctr) / max(before_ctr, 0.001)
    impression_change = (after_impressions - before_impressions) / before_impressions
    signal = max(clicks_change, ctr_change)
    negative_signal = min(clicks_change, ctr_change)
    if signal >= 0.10 and negative_signal > -0.10 and impression_change > -0.20:
        outcome = "positive"
    elif negative_signal <= -0.10 and signal < 0.10 and impression_change < 0.20:
        outcome = "negative"
    else:
        outcome = "neutral"
    delta = {
        "clicks_change": round(clicks_change, 4),
        "ctr_change": round(ctr_change, 4),
        "impressions_change": round(impression_change, 4),
    }
    confidence = min(95, 40 + int(min(before_impressions, after_impressions) ** 0.5 * 3))
    return outcome, delta, confidence


def detect_opportunity_candidates(
    rows: list[SearchAnalyticsMetric],
    *,
    period_end: date,
) -> list[OpportunityCandidate]:
    recent_start = period_end - timedelta(days=27)
    current_start = period_end - timedelta(days=13)
    previous_start = period_end - timedelta(days=27)
    previous_end = current_start - timedelta(days=1)
    recent: dict[tuple[str, str], list[SearchAnalyticsMetric]] = defaultdict(list)
    current: dict[tuple[str, str], list[SearchAnalyticsMetric]] = defaultdict(list)
    previous: dict[tuple[str, str], list[SearchAnalyticsMetric]] = defaultdict(list)
    by_query: dict[str, dict[str, list[SearchAnalyticsMetric]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        key = (row.query, row.page_url)
        if recent_start <= row.metric_date <= period_end:
            recent[key].append(row)
            by_query[row.query][row.page_url].append(row)
        if current_start <= row.metric_date <= period_end:
            current[key].append(row)
        if previous_start <= row.metric_date <= previous_end:
            previous[key].append(row)

    candidates: list[OpportunityCandidate] = []
    for (query, page_url), grouped in recent.items():
        metrics = _weighted_metrics(grouped)
        if metrics["impressions"] >= 100 and 1 <= metrics["position"] <= 10 and metrics["ctr"] < 0.02:
            candidates.append(
                OpportunityCandidate(
                    "low_ctr", query, page_url,
                    f"Improve click-through rate for “{query}”",
                    min(100, 55 + int(metrics["impressions"] / 100)),
                    min(95, 60 + int(metrics["impressions"] ** 0.5)),
                    metrics,
                )
            )
        if metrics["impressions"] >= 50 and 11 <= metrics["position"] <= 20:
            candidates.append(
                OpportunityCandidate(
                    "striking_distance", query, page_url,
                    f"Move “{query}” onto page one",
                    min(100, 50 + int(metrics["impressions"] / 75)),
                    min(95, 55 + int(metrics["impressions"] ** 0.5)),
                    metrics,
                )
            )

        old = _weighted_metrics(previous.get((query, page_url), []))
        new = _weighted_metrics(current.get((query, page_url), []))
        if old["clicks"] >= 10 and new["clicks"] <= old["clicks"] * 0.70:
            decay = round((new["clicks"] - old["clicks"]) / old["clicks"], 4)
            candidates.append(
                OpportunityCandidate(
                    "traffic_decay", query, page_url,
                    f"Recover declining traffic for “{query}”",
                    min(100, 65 + int(abs(decay) * 30)),
                    min(95, 65 + int(old["clicks"] ** 0.5)),
                    {"previous": old, "current": new, "clicks_change": decay},
                )
            )

    for query, pages in by_query.items():
        qualified = [
            (page_url, _weighted_metrics(grouped))
            for page_url, grouped in pages.items()
            if _weighted_metrics(grouped)["impressions"] >= 20
        ]
        if query and len(qualified) >= 2:
            qualified.sort(key=lambda item: item[1]["impressions"], reverse=True)
            total_impressions = sum(item[1]["impressions"] for item in qualified)
            candidates.append(
                OpportunityCandidate(
                    "cannibalization", query, None,
                    f"Resolve competing pages for “{query}”",
                    min(100, 60 + len(qualified) * 5),
                    min(95, 60 + int(total_impressions ** 0.5)),
                    {"pages": [{"page_url": url, **metrics} for url, metrics in qualified[:10]]},
                )
            )
    return candidates


async def _detect_opportunity_candidates_from_db(
    db: AsyncSession,
    *,
    site_id: uuid.UUID,
    period_end: date,
) -> list[OpportunityCandidate]:
    """Aggregate in PostgreSQL so high-cardinality properties do not ORM-load raw days."""
    recent_start = period_end - timedelta(days=27)
    current_start = period_end - timedelta(days=13)
    previous_end = current_start - timedelta(days=1)
    previous_clicks = func.sum(
        case(
            (SearchAnalyticsMetric.metric_date <= previous_end, SearchAnalyticsMetric.clicks),
            else_=0,
        )
    )
    statement = (
        select(
            SearchAnalyticsMetric.query,
            SearchAnalyticsMetric.page_url,
            func.sum(SearchAnalyticsMetric.clicks).label("clicks"),
            func.sum(SearchAnalyticsMetric.impressions).label("impressions"),
            func.sum(
                SearchAnalyticsMetric.position * SearchAnalyticsMetric.impressions
            ).label("weighted_position"),
            previous_clicks.label("previous_clicks"),
            func.sum(
                case(
                    (
                        SearchAnalyticsMetric.metric_date <= previous_end,
                        SearchAnalyticsMetric.impressions,
                    ),
                    else_=0,
                )
            ).label("previous_impressions"),
            func.sum(
                case(
                    (
                        SearchAnalyticsMetric.metric_date <= previous_end,
                        SearchAnalyticsMetric.position * SearchAnalyticsMetric.impressions,
                    ),
                    else_=0,
                )
            ).label("previous_weighted_position"),
            func.sum(
                case(
                    (
                        SearchAnalyticsMetric.metric_date >= current_start,
                        SearchAnalyticsMetric.clicks,
                    ),
                    else_=0,
                )
            ).label("current_clicks"),
            func.sum(
                case(
                    (
                        SearchAnalyticsMetric.metric_date >= current_start,
                        SearchAnalyticsMetric.impressions,
                    ),
                    else_=0,
                )
            ).label("current_impressions"),
            func.sum(
                case(
                    (
                        SearchAnalyticsMetric.metric_date >= current_start,
                        SearchAnalyticsMetric.position * SearchAnalyticsMetric.impressions,
                    ),
                    else_=0,
                )
            ).label("current_weighted_position"),
        )
        .where(
            SearchAnalyticsMetric.site_id == site_id,
            SearchAnalyticsMetric.metric_date.between(recent_start, period_end),
        )
        .group_by(SearchAnalyticsMetric.query, SearchAnalyticsMetric.page_url)
        .having(
            or_(
                func.sum(SearchAnalyticsMetric.impressions) >= 20,
                previous_clicks >= 10,
            )
        )
    )
    grouped = (await db.execute(statement)).all()

    def metrics(clicks: float, impressions: float, weighted: float) -> dict[str, float]:
        clicks_value = float(clicks or 0)
        impression_value = float(impressions or 0)
        return {
            "clicks": round(clicks_value, 3),
            "impressions": round(impression_value, 3),
            "ctr": round(clicks_value / impression_value, 6) if impression_value else 0.0,
            "position": round(float(weighted or 0) / impression_value, 3)
            if impression_value
            else 0.0,
        }

    candidates: list[OpportunityCandidate] = []
    by_query: dict[str, list[tuple[str, dict[str, float]]]] = defaultdict(list)
    for row in grouped:
        recent = metrics(row.clicks, row.impressions, row.weighted_position)
        if recent["impressions"] >= 20:
            by_query[row.query].append((row.page_url, recent))
        if recent["impressions"] >= 100 and 1 <= recent["position"] <= 10 and recent["ctr"] < 0.02:
            candidates.append(
                OpportunityCandidate(
                    "low_ctr", row.query, row.page_url,
                    f"Improve click-through rate for “{row.query}”",
                    min(100, 55 + int(recent["impressions"] / 100)),
                    min(95, 60 + int(recent["impressions"] ** 0.5)),
                    recent,
                )
            )
        if recent["impressions"] >= 50 and 11 <= recent["position"] <= 20:
            candidates.append(
                OpportunityCandidate(
                    "striking_distance", row.query, row.page_url,
                    f"Move “{row.query}” onto page one",
                    min(100, 50 + int(recent["impressions"] / 75)),
                    min(95, 55 + int(recent["impressions"] ** 0.5)),
                    recent,
                )
            )
        previous = metrics(
            row.previous_clicks,
            row.previous_impressions,
            row.previous_weighted_position,
        )
        current = metrics(
            row.current_clicks,
            row.current_impressions,
            row.current_weighted_position,
        )
        if previous["clicks"] >= 10 and current["clicks"] <= previous["clicks"] * 0.70:
            decay = round(
                (current["clicks"] - previous["clicks"]) / previous["clicks"],
                4,
            )
            candidates.append(
                OpportunityCandidate(
                    "traffic_decay", row.query, row.page_url,
                    f"Recover declining traffic for “{row.query}”",
                    min(100, 65 + int(abs(decay) * 30)),
                    min(95, 65 + int(previous["clicks"] ** 0.5)),
                    {"previous": previous, "current": current, "clicks_change": decay},
                )
            )
    for query, pages in by_query.items():
        if query and len(pages) >= 2:
            pages.sort(key=lambda item: item[1]["impressions"], reverse=True)
            total_impressions = sum(item[1]["impressions"] for item in pages)
            candidates.append(
                OpportunityCandidate(
                    "cannibalization", query, None,
                    f"Resolve competing pages for “{query}”",
                    min(100, 60 + len(pages) * 5),
                    min(95, 60 + int(total_impressions ** 0.5)),
                    {"pages": [{"page_url": url, **value} for url, value in pages[:10]]},
                )
            )
    return candidates


async def _signal_job(job_id: uuid.UUID) -> None:
    if not settings.redis_url:
        return
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis.rpush(settings.search_sync_queue_key, str(job_id))
        await redis.ltrim(settings.search_sync_queue_key, -1000, -1)
        await redis.expire(settings.search_sync_queue_key, 86400)
    except Exception as exc:
        logger.warning("Search sync Redis signal failed: %s", type(exc).__name__)
    finally:
        await redis.aclose()


async def enqueue_search_sync(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    site_id: uuid.UUID,
    source: str = "operator",
) -> tuple[JobQueue, bool]:
    site = await db.scalar(select(Site).where(Site.id == site_id).with_for_update())
    if not site or site.workspace_id != workspace_id:
        raise SearchPerformanceError("Site not found in this workspace", 404)
    connection = await db.scalar(
        select(GoogleDataConnection).where(GoogleDataConnection.workspace_id == workspace_id)
    )
    if not connection or connection.status != "configured" or not connection.gsc_property:
        raise SearchPerformanceError("Configure a Search Console property before synchronizing", 409)
    if not _property_matches_site(connection.gsc_property, site.domain):
        raise SearchPerformanceError("The selected Search Console property does not cover this site", 409)
    active = await db.scalar(
        select(JobQueue).where(
            JobQueue.site_id == site_id,
            JobQueue.job_type == "gsc_search_sync",
            JobQueue.status.in_(ACTIVE_STATUSES),
        ).limit(1)
    )
    if active:
        return active, True
    if settings.search_sync_min_interval_minutes:
        recent = await db.scalar(
            select(JobQueue)
            .where(
                JobQueue.site_id == site_id,
                JobQueue.job_type == "gsc_search_sync",
                JobQueue.created_at
                >= _now() - timedelta(minutes=settings.search_sync_min_interval_minutes),
            )
            .order_by(JobQueue.created_at.desc())
            .limit(1)
        )
        if recent:
            if recent.status == "completed":
                return recent, True
            retry_at = recent.created_at + timedelta(
                minutes=settings.search_sync_min_interval_minutes
            )
            retry_after = max(1, int((retry_at - _now()).total_seconds()) + 1)
            raise SearchPerformanceError(
                "A Search Console synchronization attempt already reserved this site; "
                "retry after the cooldown window",
                429,
                code="search_sync_cooldown",
                retry_after_seconds=retry_after,
            )
    end_date = date.today() - timedelta(days=settings.search_sync_finalization_lag_days)
    start_date = end_date - timedelta(days=settings.search_sync_lookback_days - 1)
    job = JobQueue(
        site_id=site_id,
        job_type="gsc_search_sync",
        status="queued",
        max_attempts=settings.search_sync_job_max_attempts,
        run_after=_now(),
        payload={
            "workspace_id": str(workspace_id),
            "connection_id": str(connection.id),
            "gsc_property": connection.gsc_property,
            "source": source,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    await _signal_job(job.id)
    return job, False


async def _fetch_search_rows(
    client: httpx.AsyncClient,
    *,
    token: str,
    property_id: str,
    metric_date: date,
) -> list[dict]:
    """Fetch one finalized day so row caps never truncate a multi-day range."""
    property_path = quote(property_id, safe="")
    rows: list[dict] = []
    start_row = 0
    while len(rows) < settings.search_sync_max_rows:
        requested_limit = min(
            settings.search_sync_page_size,
            settings.search_sync_max_rows - len(rows),
        )
        response = await client.post(
            f"{settings.google_search_console_api_url}/sites/{property_path}/searchAnalytics/query",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "startDate": metric_date.isoformat(),
                "endDate": metric_date.isoformat(),
                "dimensions": ["date", "query", "page"],
                "rowLimit": requested_limit,
                "startRow": start_row,
                "dataState": "final",
            },
        )
        if response.status_code >= 400:
            raise GoogleDataServiceError(
                f"Search Console sync returned HTTP {response.status_code}",
                502,
            )
        batch = response.json().get("rows", [])
        if not batch:
            break
        rows.extend(batch)
        if len(rows) >= settings.search_sync_max_rows and len(batch) == requested_limit:
            probe = await client.post(
                f"{settings.google_search_console_api_url}/sites/{property_path}/searchAnalytics/query",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "startDate": metric_date.isoformat(),
                    "endDate": metric_date.isoformat(),
                    "dimensions": ["date", "query", "page"],
                    "rowLimit": 1,
                    "startRow": len(rows),
                    "dataState": "final",
                },
            )
            if probe.status_code >= 400:
                raise GoogleDataServiceError(
                    f"Search Console cap probe returned HTTP {probe.status_code}",
                    502,
                )
            if probe.json().get("rows"):
                raise SearchPerformanceError(
                    f"Search Console daily row cap was reached for {metric_date.isoformat()}; "
                    "increase SEARCH_SYNC_MAX_ROWS to avoid a partial replacement",
                    409,
                    code="daily_row_cap",
                )
            break
        if len(batch) < requested_limit:
            break
        start_row += len(batch)
    return rows


async def _resolve_finalized_end_date(
    client: httpx.AsyncClient,
    *,
    token: str,
    property_id: str,
    proposed_end: date,
) -> date:
    """Use GSC incomplete-data metadata to keep declared coverage conservative."""
    property_path = quote(property_id, safe="")
    response = await client.post(
        f"{settings.google_search_console_api_url}/sites/{property_path}/searchAnalytics/query",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "startDate": (proposed_end - timedelta(days=7)).isoformat(),
            "endDate": proposed_end.isoformat(),
            "dimensions": ["date"],
            "rowLimit": 8,
            "startRow": 0,
            "dataState": "all",
        },
    )
    if response.status_code >= 400:
        raise GoogleDataServiceError(
            f"Search Console finalization probe returned HTTP {response.status_code}",
            502,
        )
    raw_boundary = (response.json().get("metadata") or {}).get("first_incomplete_date")
    if not raw_boundary:
        return proposed_end
    try:
        finalized_end = date.fromisoformat(str(raw_boundary)) - timedelta(days=1)
    except ValueError as exc:
        raise SearchPerformanceError(
            "Search Console returned invalid finalization metadata",
            502,
            code="invalid_finalization_metadata",
        ) from exc
    return min(proposed_end, finalized_end)


async def _persist_search_rows(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    site_id: uuid.UUID,
    site_domain: str,
    start_date: date,
    end_date: date,
    rows: list[dict],
) -> int:
    values: list[dict] = []
    for row in rows:
        keys = row.get("keys") or []
        if len(keys) < 3:
            continue
        try:
            metric_date = date.fromisoformat(str(keys[0]))
        except ValueError:
            continue
        if _host(str(keys[2])) != _host(site_domain):
            continue
        raw_query = str(keys[1])
        raw_page_url = str(keys[2])
        query = raw_query[:10_000]
        page_url = raw_page_url[:2048]
        values.append(
            {
                "workspace_id": workspace_id,
                "site_id": site_id,
                "metric_date": metric_date,
                "query": query,
                "query_hash": hashlib.sha256(raw_query.encode()).hexdigest(),
                "page_url": page_url,
                "page_url_hash": hashlib.sha256(raw_page_url.encode()).hexdigest(),
                "page_url_key_hash": hashlib.sha256(
                    _page_url_key(raw_page_url).encode()
                ).hexdigest(),
                "clicks": float(row.get("clicks") or 0),
                "impressions": float(row.get("impressions") or 0),
                "ctr": float(row.get("ctr") or 0),
                "position": float(row.get("position") or 0),
            }
        )
    await db.execute(
        delete(SearchAnalyticsMetric).where(
            SearchAnalyticsMetric.site_id == site_id,
            SearchAnalyticsMetric.metric_date.between(start_date, end_date),
        )
    )
    for offset in range(0, len(values), 2_000):
        await db.execute(insert(SearchAnalyticsMetric), values[offset : offset + 2_000])
    return len(values)


async def reconcile_search_opportunities(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    site_id: uuid.UUID,
    period_end: date | None = None,
) -> list[SearchOpportunity]:
    if period_end is not None:
        end = period_end
    else:
        latest_sync = await db.scalar(
            select(JobQueue)
            .where(
                JobQueue.site_id == site_id,
                JobQueue.job_type == "gsc_search_sync",
                JobQueue.status == "completed",
            )
            .order_by(JobQueue.completed_at.desc())
            .limit(1)
        )
        try:
            end = date.fromisoformat(str((latest_sync.payload or {})["end_date"])) if latest_sync else None
        except (KeyError, ValueError):
            end = None
        end = end or date.today() - timedelta(days=settings.search_sync_finalization_lag_days)
    candidates = await _detect_opportunity_candidates_from_db(
        db,
        site_id=site_id,
        period_end=end,
    )
    measured_windows = list(
        (
            await db.execute(
                select(ActionMeasurement)
                .join(OperatorAction, OperatorAction.id == ActionMeasurement.action_id)
                .where(
                    ActionMeasurement.site_id == site_id,
                    ActionMeasurement.status == "measured",
                    ActionMeasurement.outcome.in_(["positive", "neutral", "negative"]),
                    ActionMeasurement.mutation_applied.is_(True),
                )
            )
        ).scalars().all()
    )
    measured_by_action: dict[uuid.UUID, ActionMeasurement] = {}
    for item in measured_windows:
        current = measured_by_action.get(item.action_id)
        if current is None or item.window_days > current.window_days:
            measured_by_action[item.action_id] = item
    measured = list(measured_by_action.values())
    positives = sum(1 for item in measured if item.outcome == "positive")
    negatives = sum(1 for item in measured if item.outcome == "negative")
    history_adjustment = (
        max(-10, min(10, round(10 * (positives - negatives) / len(measured))))
        if len(measured) >= 3
        else 0
    )
    existing = list(
        (
            await db.execute(
                select(SearchOpportunity).where(
                    SearchOpportunity.workspace_id == workspace_id,
                    SearchOpportunity.site_id == site_id,
                )
            )
        ).scalars().all()
    )
    by_key = {item.opportunity_key: item for item in existing}
    seen: set[str] = set()
    now = _now()
    active: list[SearchOpportunity] = []
    for candidate in candidates:
        seen.add(candidate.key)
        record = by_key.get(candidate.key)
        if record is None:
            record = SearchOpportunity(
                workspace_id=workspace_id,
                site_id=site_id,
                opportunity_key=candidate.key,
                opportunity_type=candidate.opportunity_type,
                first_detected_at=now,
            )
            db.add(record)
        record.status = "active"
        record.title = candidate.title[:500]
        record.query = candidate.query
        record.page_url = candidate.page_url
        record.priority_score = max(0, min(100, candidate.priority_score + history_adjustment))
        record.confidence_score = candidate.confidence_score
        record.metrics = candidate.metrics
        record.evidence = [
            {"source": "gsc_search_analytics", "period_end": end.isoformat()},
            {
                "source": "historical_action_outcomes",
                "samples": len(measured),
                "positive": positives,
                "negative": negatives,
                "priority_adjustment": history_adjustment,
            },
        ]
        record.last_detected_at = now
        record.resolved_at = None
        active.append(record)
    resolved: list[SearchOpportunity] = []
    for record in existing:
        if (
            record.status == "active"
            and record.opportunity_type in SEARCH_ANALYTICS_OPPORTUNITY_TYPES
            and record.opportunity_key not in seen
        ):
            record.status = "resolved"
            record.resolved_at = now
            resolved.append(record)
    await db.flush()
    await _reconcile_opportunity_actions(
        db,
        workspace_id=workspace_id,
        site_id=site_id,
        opportunities=sorted(
            active,
            key=lambda item: (-item.priority_score, -item.confidence_score, str(item.id)),
        )[: settings.search_opportunity_action_limit],
        resolved=resolved,
    )
    return active


async def _reconcile_opportunity_actions(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    site_id: uuid.UUID,
    opportunities: list[SearchOpportunity],
    resolved: list[SearchOpportunity],
) -> int:
    """Keep a bounded, governed draft queue aligned with active search findings."""
    created = 0
    actions = list(
        (
            await db.execute(
                select(OperatorAction).where(
                    OperatorAction.workspace_id == workspace_id,
                    OperatorAction.site_id == site_id,
                    OperatorAction.source == "gsc_opportunity_pipeline",
                )
            )
        ).scalars().all()
    )
    by_key = {action.idempotency_key: action for action in actions if action.idempotency_key}
    for opportunity in opportunities:
        key = f"gsc:{site_id.hex}:{opportunity.opportunity_key}"
        evidence = [
            {
                "type": "search_opportunity",
                "opportunity_id": str(opportunity.id),
                "opportunity_type": opportunity.opportunity_type,
                "query": opportunity.query,
                "url": opportunity.page_url,
                "metrics": opportunity.metrics or {},
            },
            *(opportunity.evidence or []),
        ]
        measurement_plan = {
            "query": opportunity.query,
            "target_url": opportunity.page_url,
            "metrics": ["clicks", "impressions", "ctr", "position"],
            "windows_days": [7, 14, 30, 60, 90],
        }
        existing_action = by_key.get(key)
        if existing_action:
            if (
                existing_action.status == "cancelled"
                and (existing_action.approval_policy or {}).get("opportunity_resolved") is True
            ):
                existing_action.status = "draft"
                existing_action.version += 1
                existing_action.approval_policy = {
                    key: value
                    for key, value in (existing_action.approval_policy or {}).items()
                    if key != "opportunity_resolved"
                }
                db.add(
                    OperatorActionEvent(
                        action_id=existing_action.id,
                        workspace_id=workspace_id,
                        site_id=site_id,
                        event_type="search_opportunity_reactivated",
                        from_status="cancelled",
                        to_status="draft",
                        actor_type="system",
                        payload={"opportunity_id": str(opportunity.id)},
                    )
                )
            if existing_action.status == "draft":
                next_title = opportunity.title[:500]
                changed = any(
                    (
                        existing_action.title != next_title,
                        (existing_action.evidence or []) != evidence,
                        existing_action.impact_score != opportunity.priority_score,
                        existing_action.confidence_score != opportunity.confidence_score,
                        (existing_action.measurement_plan or {}) != measurement_plan,
                    )
                )
                if changed:
                    existing_action.title = next_title
                    existing_action.evidence = evidence
                    existing_action.impact_score = opportunity.priority_score
                    existing_action.confidence_score = opportunity.confidence_score
                    existing_action.measurement_plan = measurement_plan
                    existing_action.version += 1
                    db.add(
                        OperatorActionEvent(
                            action_id=existing_action.id,
                            workspace_id=workspace_id,
                            site_id=site_id,
                            event_type="search_opportunity_refreshed",
                            from_status="draft",
                            to_status="draft",
                            actor_type="system",
                            payload={
                                "opportunity_id": str(opportunity.id),
                                "priority_score": opportunity.priority_score,
                                "confidence_score": opportunity.confidence_score,
                            },
                        )
                    )
            continue
        result = await db.execute(
            insert(OperatorAction)
            .values(
                workspace_id=workspace_id,
                site_id=site_id,
                action_type="search_performance_recommendation",
                category="search_performance",
                source="gsc_opportunity_pipeline",
                status="draft",
                title=opportunity.title[:500],
                description=(
                    "Review this Search Console opportunity, approve a concrete change, "
                    "and measure its effect against frozen baselines."
                ),
                evidence=evidence,
                plan={
                    "objective": opportunity.title,
                    "steps": [
                        "review Search Console evidence",
                        "prepare the smallest reversible content or internal-link change",
                        "request operator approval",
                        "validate the affected page",
                    ],
                },
                impact_score=opportunity.priority_score,
                confidence_score=opportunity.confidence_score,
                effort_score=30,
                risk_score=10,
                risk_level="low",
                approval_policy={"mode": "manual", "reason": "search_performance_change"},
                requires_approval=True,
                execution_target={
                    "adapter": "simulation",
                    "opportunity_id": str(opportunity.id),
                    "target_url": opportunity.page_url,
                },
                proposed_diff={
                    "mode": "recommendation_only",
                    "affected_urls": [opportunity.page_url] if opportunity.page_url else [],
                },
                rollback_plan={"strategy": "restore_before_snapshot"},
                measurement_plan=measurement_plan,
                validation_checklist=[
                    "affected page remains reachable",
                    "canonical and robots directives remain valid",
                    "measurement target matches the approved change",
                ],
                idempotency_key=key,
            )
            .on_conflict_do_nothing(
                index_elements=["workspace_id", "idempotency_key"]
            )
            .returning(OperatorAction.id)
        )
        action_id = result.scalar_one_or_none()
        if action_id is None:
            continue
        db.add(
            OperatorActionEvent(
                action_id=action_id,
                workspace_id=workspace_id,
                site_id=site_id,
                event_type="action_created",
                from_status=None,
                to_status="draft",
                actor_user_id=None,
                actor_type="system",
                payload={
                    "source": "gsc_opportunity_pipeline",
                    "opportunity_id": str(opportunity.id),
                    "action_type": "search_performance_recommendation",
                },
            )
        )
        created += 1

    resolved_keys = {
        f"gsc:{site_id.hex}:{opportunity.opportunity_key}": opportunity
        for opportunity in resolved
    }
    for key, opportunity in resolved_keys.items():
        action = by_key.get(key)
        if not action or action.status != "draft":
            continue
        action.status = "cancelled"
        action.version += 1
        action.approval_policy = {
            **(action.approval_policy or {}),
            "opportunity_resolved": True,
        }
        db.add(
            OperatorActionEvent(
                action_id=action.id,
                workspace_id=workspace_id,
                site_id=site_id,
                event_type="search_opportunity_resolved",
                from_status="draft",
                to_status="cancelled",
                actor_type="system",
                payload={"opportunity_id": str(opportunity.id)},
            )
        )
    await db.flush()
    return created


async def _claim_search_sync_job(db: AsyncSession) -> JobQueue | None:
    now = _now()
    job = await db.scalar(
        select(JobQueue)
        .where(
            JobQueue.job_type == "gsc_search_sync",
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
    job.lease_expires_at = now + timedelta(seconds=settings.search_sync_job_lease_seconds)
    job.started_at = job.started_at or now
    job.attempt_count += 1
    db.add(
        SearchSyncAttempt(
            job_id=job.id,
            attempt_number=job.attempt_count,
            worker_id=WORKER_ID,
        )
    )
    await db.commit()
    await db.refresh(job)
    return job


async def _process_search_sync_job(db: AsyncSession, job_id: uuid.UUID) -> JobQueue:
    job = await db.get(JobQueue, job_id)
    if not job or job.status != "running" or job.lease_owner != WORKER_ID:
        raise SearchPerformanceError("Search sync job lease is unavailable", 409)
    payload = job.payload or {}
    try:
        workspace_id = uuid.UUID(str(payload["workspace_id"]))
        connection_id = uuid.UUID(str(payload["connection_id"]))
        start_date = date.fromisoformat(str(payload["start_date"]))
        end_date = date.fromisoformat(str(payload["end_date"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise SearchPerformanceError(
            "Search sync job configuration is invalid",
            409,
            code="invalid_job_configuration",
        ) from exc
    expected_property = str(payload.get("gsc_property") or "")
    connection = await db.get(GoogleDataConnection, connection_id)
    site = await db.get(Site, job.site_id)
    if (
        not connection
        or connection.workspace_id != workspace_id
        or connection.status != "configured"
        or connection.gsc_property != expected_property
        or not site
        or site.workspace_id != workspace_id
        or not _property_matches_site(expected_property, site.domain)
    ):
        raise SearchPerformanceError(
            "Search Console connection is unavailable",
            409,
            code="invalid_sync_scope",
        )
    token = await _access_token(db, connection)
    # Token refresh may commit; reload without row locks so the separate heartbeat
    # can extend this long-running, day-partitioned job during remote I/O.
    connection = await db.get(GoogleDataConnection, connection.id)
    site = await db.get(Site, job.site_id)
    if (
        not connection
        or connection.workspace_id != workspace_id
        or connection.status != "configured"
        or connection.gsc_property != expected_property
        or not site
        or site.workspace_id != workspace_id
        or not _property_matches_site(expected_property, site.domain)
    ):
        raise SearchPerformanceError(
            "Search Console connection changed before synchronization",
            409,
            code="invalid_sync_scope",
        )
    stored = 0
    fetched_total = 0
    async with httpx.AsyncClient(
        timeout=settings.google_integration_timeout_seconds,
        follow_redirects=False,
    ) as client:
        end_date = await _resolve_finalized_end_date(
            client,
            token=token,
            property_id=expected_property,
            proposed_end=end_date,
        )
        if end_date >= date.today():
            raise SearchPerformanceError(
                "Search Console finalization boundary is unsafe",
                502,
                code="unsafe_finalization_boundary",
            )
        start_date = end_date - timedelta(days=settings.search_sync_lookback_days - 1)
        job.payload = {
            **payload,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "data_state": "final",
        }
        cursor = start_date
        while cursor <= end_date:
            rows = await _fetch_search_rows(
                client,
                token=token,
                property_id=expected_property,
                metric_date=cursor,
            )
            fetched_total += len(rows)
            if fetched_total > settings.search_sync_max_total_rows:
                raise SearchPerformanceError(
                    "Search Console job row cap was reached; narrow the lookback or raise "
                    "SEARCH_SYNC_MAX_TOTAL_ROWS after a capacity review",
                    409,
                    code="job_row_cap",
                )
            stored += await _persist_search_rows(
                db,
                workspace_id=workspace_id,
                site_id=job.site_id,
                site_domain=site.domain,
                start_date=cursor,
                end_date=cursor,
                rows=rows,
            )
            cursor += timedelta(days=1)

    # Revalidate the mutable property and site after all remote I/O. All daily
    # replacements above are still uncommitted and roll back together on change.
    job = await db.scalar(
        select(JobQueue)
        .where(JobQueue.id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not job or job.status != "running" or job.lease_owner != WORKER_ID:
        raise SearchPerformanceError("Search sync worker lost its lease", 409)
    connection = await db.scalar(
        select(GoogleDataConnection)
        .where(GoogleDataConnection.id == connection.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    site = await db.scalar(
        select(Site)
        .where(Site.id == job.site_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        not connection
        or connection.workspace_id != workspace_id
        or connection.status != "configured"
        or connection.gsc_property != expected_property
        or not site
        or site.workspace_id != workspace_id
        or not _property_matches_site(expected_property, site.domain)
    ):
        raise SearchPerformanceError(
            "Search Console property changed while this job was running; no metrics were replaced",
            409,
            code="invalid_sync_scope",
        )
    opportunities = await reconcile_search_opportunities(
        db,
        workspace_id=workspace_id,
        site_id=job.site_id,
        period_end=end_date,
    )
    summary_window = await _metric_window(
        db,
        site_id=job.site_id,
        start=end_date - timedelta(days=27),
        end=end_date,
        query=None,
        target_url=None,
    )
    summary = {
        key: summary_window[key]
        for key in ("clicks", "impressions", "ctr", "position")
    }
    connection.baseline_status = "ready"
    connection.baseline_summary = {
        **(connection.baseline_summary or {}),
        "period": {
            "start_date": (end_date - timedelta(days=27)).isoformat(),
            "end_date": end_date.isoformat(),
        },
        "gsc": {"property": connection.gsc_property, **summary},
        "durable_search_sync": {
            "rows": stored,
            "opportunities": len(opportunities),
            "lookback_days": settings.search_sync_lookback_days,
        },
    }
    connection.last_synced_at = _now()
    connection.last_error = None
    # Make this transaction's complete, non-truncated range visible to coverage checks.
    # A later error still rolls the status and replacement back atomically.
    job.status = "completed"
    job.completed_at = _now()
    due_action_ids = (
        select(ActionMeasurement.action_id)
        .join(OperatorAction, OperatorAction.id == ActionMeasurement.action_id)
        .where(
            OperatorAction.site_id == job.site_id,
            ActionMeasurement.status.in_(["baseline_pending", "waiting"]),
        )
        .group_by(ActionMeasurement.action_id)
        .order_by(func.min(ActionMeasurement.last_checked_at).asc().nullsfirst())
        .limit(50)
    )
    measurement_actions = list(
        (
            await db.execute(
                select(OperatorAction)
                .where(OperatorAction.id.in_(due_action_ids))
                .order_by(OperatorAction.id.asc())
            )
        ).scalars().all()
    )
    for action in measurement_actions:
        await refresh_action_measurements(db, action)
    result = {
        "rows": stored,
        "rows_fetched": fetched_total,
        "opportunities": len(opportunities),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "metrics": summary,
        "measurement_actions_refreshed": len(measurement_actions),
    }
    job.result = result
    job.lease_owner = None
    job.lease_expires_at = None
    attempt = await db.scalar(
        select(SearchSyncAttempt).where(
            SearchSyncAttempt.job_id == job.id,
            SearchSyncAttempt.attempt_number == job.attempt_count,
        )
    )
    if attempt:
        attempt.status = "completed"
        attempt.result = result
        attempt.completed_at = _now()
    await db.commit()
    await db.refresh(job)
    return job


async def recover_expired_search_sync_leases(db: AsyncSession) -> int:
    now = _now()
    jobs = list(
        (
            await db.execute(
                select(JobQueue).where(
                    JobQueue.job_type == "gsc_search_sync",
                    JobQueue.status == "running",
                    JobQueue.lease_expires_at < now,
                ).with_for_update(skip_locked=True)
            )
        ).scalars().all()
    )
    for job in jobs:
        job.status = "retry_wait" if job.attempt_count < job.max_attempts else "failed"
        job.run_after = now
        job.error_code = "lease_expired"
        job.error_message = "Search sync worker lease expired"
        job.lease_owner = None
        job.lease_expires_at = None
        if job.status == "failed":
            job.completed_at = now
        attempt = await db.scalar(
            select(SearchSyncAttempt).where(
                SearchSyncAttempt.job_id == job.id,
                SearchSyncAttempt.attempt_number == job.attempt_count,
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


async def _heartbeat_search_sync_job(job_id: uuid.UUID, stop: asyncio.Event) -> None:
    interval = max(1.0, settings.search_sync_job_lease_seconds / 3)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            break
        except TimeoutError:
            pass
        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    update(JobQueue)
                    .where(
                        JobQueue.id == job_id,
                        JobQueue.job_type == "gsc_search_sync",
                        JobQueue.status == "running",
                        JobQueue.lease_owner == WORKER_ID,
                    )
                    .values(
                        heartbeat_at=_now(),
                        lease_expires_at=_now() + timedelta(seconds=settings.search_sync_job_lease_seconds),
                    )
                )
                await db.commit()
                if result.rowcount != 1:
                    break
        except Exception as exc:
            logger.warning("Search sync heartbeat failed for %s: %s", job_id, type(exc).__name__)


async def run_search_sync_worker_tick() -> int:
    await _consume_job_hints()
    async with async_session_factory() as db:
        await recover_expired_search_sync_leases(db)
    processed = 0
    for _ in range(settings.search_sync_worker_batch_size):
        async with async_session_factory() as db:
            job = await _claim_search_sync_job(db)
        if not job:
            break
        stop_heartbeat = asyncio.Event()
        heartbeat = asyncio.create_task(_heartbeat_search_sync_job(job.id, stop_heartbeat))
        try:
            async with async_session_factory() as db:
                await _process_search_sync_job(db, job.id)
        except Exception as exc:
            logger.exception("Search sync job %s failed", job.id)
            async with async_session_factory() as db:
                failed = await db.scalar(select(JobQueue).where(JobQueue.id == job.id).with_for_update())
                if failed and failed.status == "running" and failed.lease_owner == WORKER_ID:
                    retryable = not isinstance(exc, SearchPerformanceError) or exc.retryable
                    failed.error_code = (
                        exc.code if isinstance(exc, SearchPerformanceError) else "search_sync_failed"
                    )
                    failed.error_message = str(exc)[:2_000]
                    failed.lease_owner = None
                    failed.lease_expires_at = None
                    if retryable and failed.attempt_count < failed.max_attempts:
                        failed.status = "retry_wait"
                        retry = min(failed.attempt_count - 1, 8)
                        failed.run_after = _now() + timedelta(
                            seconds=settings.search_sync_retry_base_seconds * (2 ** retry)
                        )
                    else:
                        failed.status = "failed"
                        failed.completed_at = _now()
                    attempt = await db.scalar(
                        select(SearchSyncAttempt).where(
                            SearchSyncAttempt.job_id == failed.id,
                            SearchSyncAttempt.attempt_number == failed.attempt_count,
                        )
                    )
                    if attempt:
                        attempt.status = "failed"
                        attempt.error_code = failed.error_code
                        attempt.error_message = failed.error_message
                        attempt.completed_at = _now()
                    await db.commit()
        finally:
            stop_heartbeat.set()
            await heartbeat
        processed += 1
    return processed


async def _consume_job_hints() -> None:
    if not settings.redis_url:
        return
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        for _ in range(max(10, settings.search_sync_worker_batch_size * 10)):
            if await redis.lpop(settings.search_sync_queue_key) is None:
                break
    except Exception as exc:
        logger.warning("Search sync Redis hint cleanup failed: %s", type(exc).__name__)
    finally:
        await redis.aclose()


def _measurement_target(action: OperatorAction) -> tuple[str | None, str | None]:
    plan = action.measurement_plan or {}
    query = plan.get("query") if isinstance(plan.get("query"), str) else None
    target_url = plan.get("target_url") if isinstance(plan.get("target_url"), str) else None
    if not target_url:
        for container in (plan, action.plan or {}, action.proposed_diff or {}):
            values = container.get("target_urls") or container.get("affected_urls")
            if isinstance(values, list) and values and isinstance(values[0], str):
                target_url = values[0]
                break
    if not target_url:
        for evidence in action.evidence or []:
            if isinstance(evidence, dict) and isinstance(evidence.get("url"), str):
                target_url = evidence["url"]
                break
    return query, target_url


def _absolute_target_url(site_domain: str, target_url: str | None) -> str | None:
    if not target_url:
        return None
    if target_url.startswith("/"):
        raw = site_domain if "://" in site_domain else f"https://{site_domain}"
        parsed = urlsplit(raw)
        relative = urlsplit(target_url)
        return urlunsplit((parsed.scheme, parsed.netloc, relative.path or "/", relative.query, ""))
    parsed = urlsplit(target_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


async def _window_was_synced(
    db: AsyncSession,
    *,
    site_id: uuid.UUID,
    start: date,
    end: date,
) -> bool:
    payloads = list(
        (
            await db.execute(
                select(JobQueue.payload).where(
                    JobQueue.site_id == site_id,
                    JobQueue.job_type == "gsc_search_sync",
                    JobQueue.status == "completed",
                    JobQueue.payload["start_date"].as_string() <= end.isoformat(),
                    JobQueue.payload["end_date"].as_string() >= start.isoformat(),
                )
            )
        ).scalars().all()
    )
    ranges: list[tuple[date, date]] = []
    for payload in payloads:
        try:
            ranges.append(
                (
                    date.fromisoformat(str((payload or {})["start_date"])),
                    date.fromisoformat(str((payload or {})["end_date"])),
                )
            )
        except (KeyError, ValueError):
            continue
    return _ranges_cover_window(ranges, start=start, end=end)


def _ranges_cover_window(
    ranges: list[tuple[date, date]],
    *,
    start: date,
    end: date,
) -> bool:
    cursor = start
    for range_start, range_end in sorted(ranges):
        if range_end < cursor:
            continue
        if range_start > cursor:
            return False
        cursor = range_end + timedelta(days=1)
        if cursor > end:
            return True
    return False


async def _metric_window(
    db: AsyncSession,
    *,
    site_id: uuid.UUID,
    start: date,
    end: date,
    query: str | None,
    target_url: str | None,
) -> dict:
    statement = select(SearchAnalyticsMetric).where(
        SearchAnalyticsMetric.site_id == site_id,
        SearchAnalyticsMetric.metric_date.between(start, end),
    )
    if query:
        statement = statement.where(SearchAnalyticsMetric.query == query)
    if target_url:
        statement = statement.where(
            SearchAnalyticsMetric.page_url_key_hash
            == hashlib.sha256(_page_url_key(target_url).encode()).hexdigest()
        )
    aggregate = (
        await db.execute(
            statement.with_only_columns(
                func.coalesce(func.sum(SearchAnalyticsMetric.clicks), 0).label("clicks"),
                func.coalesce(func.sum(SearchAnalyticsMetric.impressions), 0).label("impressions"),
                func.coalesce(
                    func.sum(SearchAnalyticsMetric.position * SearchAnalyticsMetric.impressions),
                    0,
                ).label("weighted_position"),
                func.count(func.distinct(SearchAnalyticsMetric.metric_date)).label("coverage_days"),
                func.min(SearchAnalyticsMetric.metric_date).label("data_from"),
                func.max(SearchAnalyticsMetric.metric_date).label("data_through"),
            )
        )
    ).one()
    clicks = float(aggregate.clicks or 0)
    impressions = float(aggregate.impressions or 0)
    return {
        "clicks": round(clicks, 3),
        "impressions": round(impressions, 3),
        "ctr": round(clicks / impressions, 6) if impressions else 0.0,
        "position": round(float(aggregate.weighted_position or 0) / impressions, 3)
        if impressions
        else 0.0,
        "coverage_days": int(aggregate.coverage_days or 0),
        "window_synced": await _window_was_synced(
            db,
            site_id=site_id,
            start=start,
            end=end,
        ),
        "data_from": aggregate.data_from.isoformat() if aggregate.data_from else None,
        "data_through": aggregate.data_through.isoformat() if aggregate.data_through else None,
    }


async def create_action_measurement_baselines(
    db: AsyncSession,
    action: OperatorAction,
) -> list[ActionMeasurement]:
    if not action.workspace_id:
        return []
    if not _action_uses_mutating_adapter(action):
        return []
    existing = list(
        (
            await db.execute(
                select(ActionMeasurement)
                .where(ActionMeasurement.action_id == action.id)
                .order_by(ActionMeasurement.window_days.asc())
            )
        ).scalars().all()
    )
    if existing:
        return existing
    query, target_url = _measurement_target(action)
    site = await db.get(Site, action.site_id)
    target_url = _absolute_target_url(site.domain, target_url) if site else None
    execution_anchor = action.execution_started_at or action.executed_at or action.completed_at
    baseline_end = (
        execution_anchor.date() - timedelta(days=1)
        if execution_anchor
        else date.today() - timedelta(days=1)
    )
    records: list[ActionMeasurement] = []
    for window in (7, 14, 30, 60, 90):
        baseline_start = baseline_end - timedelta(days=window - 1)
        metrics = await _metric_window(
            db,
            site_id=action.site_id,
            start=baseline_start,
            end=baseline_end,
            query=query,
            target_url=target_url,
        )
        record = ActionMeasurement(
            action_id=action.id,
            workspace_id=action.workspace_id,
            site_id=action.site_id,
            window_days=window,
            target_query=query,
            target_url=target_url,
            baseline_start=baseline_start,
            baseline_end=baseline_end,
            baseline_metrics=metrics,
            status=(
                "waiting"
                if bool(metrics.get("window_synced"))
                else "baseline_pending"
            ),
        )
        db.add(record)
        records.append(record)
    await db.flush()
    return records


async def mark_action_measurement_mutation_applied(
    db: AsyncSession,
    action: OperatorAction,
    *,
    mutation_applied: bool,
) -> None:
    """Persist the positive treatment marker used by measurement and learning."""
    records = list(
        (
            await db.execute(
                select(ActionMeasurement).where(ActionMeasurement.action_id == action.id)
            )
        ).scalars().all()
    )
    for record in records:
        record.mutation_applied = bool(mutation_applied)
        if not mutation_applied:
            record.status = "not_applicable"
            record.outcome = "insufficient_data"
    if records:
        await db.flush()


async def refreeze_action_measurement_baselines(
    db: AsyncSession,
    action: OperatorAction,
) -> list[ActionMeasurement]:
    """Freeze the actual pre-treatment window immediately before adapter apply."""
    if not action.workspace_id or not action.execution_started_at:
        return []
    records = await create_action_measurement_baselines(db, action)
    query, target_url = _measurement_target(action)
    site = await db.get(Site, action.site_id)
    target_url = _absolute_target_url(site.domain, target_url) if site else None
    baseline_end = action.execution_started_at.date() - timedelta(days=1)
    for record in records:
        record.target_query = query
        record.target_url = target_url
        record.baseline_end = baseline_end
        record.baseline_start = baseline_end - timedelta(days=record.window_days - 1)
        record.baseline_metrics = await _metric_window(
            db,
            site_id=record.site_id,
            start=record.baseline_start,
            end=record.baseline_end,
            query=query,
            target_url=target_url,
        )
        record.status = (
            "waiting" if bool(record.baseline_metrics.get("window_synced")) else "baseline_pending"
        )
        record.outcome = "insufficient_data"
        record.comparison_start = None
        record.comparison_end = None
        record.comparison_metrics = {}
        record.delta = {}
        record.confidence_score = 0
        record.measured_at = None
    await db.flush()
    return records


async def refresh_action_measurements(
    db: AsyncSession,
    action: OperatorAction,
) -> list[ActionMeasurement]:
    existing = list(
        (
            await db.execute(
                select(ActionMeasurement)
                .where(ActionMeasurement.action_id == action.id)
                .order_by(ActionMeasurement.window_days.asc())
            )
        ).scalars().all()
    )
    if not _action_uses_mutating_adapter(action):
        checked_at = _now()
        for record in existing:
            record.status = "not_applicable"
            record.outcome = "insufficient_data"
            record.last_checked_at = checked_at
        if existing:
            await db.flush()
        return existing
    if existing and action.executed_at and not any(record.mutation_applied for record in existing):
        checked_at = _now()
        for record in existing:
            record.status = "not_applicable"
            record.outcome = "insufficient_data"
            record.last_checked_at = checked_at
        await db.flush()
        return existing
    measurable_statuses = {
        "execution_queued", "executing", "validating", "succeeded",
        "rollback_queued", "rolling_back", "rolled_back", "failed",
    }
    if not existing and action.status not in measurable_statuses:
        return []
    records = await create_action_measurement_baselines(db, action)
    checked_at = _now()
    for record in records:
        record.last_checked_at = checked_at
    for record in records:
        refreshed_baseline = await _metric_window(
            db,
            site_id=record.site_id,
            start=record.baseline_start,
            end=record.baseline_end,
            query=record.target_query,
            target_url=record.target_url,
        )
        old_synced = bool((record.baseline_metrics or {}).get("window_synced"))
        new_synced = bool(refreshed_baseline.get("window_synced"))
        if new_synced or not old_synced:
            record.baseline_metrics = refreshed_baseline
        if new_synced and record.status == "baseline_pending":
            record.status = "waiting"
    measurement_anchor = action.completed_at or action.executed_at
    if not measurement_anchor:
        if action.status in {"cancelled", "failed", "rejected", "blocked", "rolled_back"}:
            for record in records:
                record.status = "not_applicable"
                record.outcome = "insufficient_data"
            await db.flush()
        return records
    rollback_at = None
    if action.status == "rolled_back":
        rollback_at = await db.scalar(
            select(OperatorActionEvent.created_at)
            .where(
                OperatorActionEvent.action_id == action.id,
                OperatorActionEvent.event_type == "action_rolled_back",
            )
            .order_by(OperatorActionEvent.created_at.desc())
            .limit(1)
        )
    available_end = date.today() - timedelta(days=settings.search_sync_finalization_lag_days)
    comparison_start = measurement_anchor.date() + timedelta(days=1)
    for record in records:
        comparison_end = comparison_start + timedelta(days=record.window_days - 1)
        if rollback_at and comparison_end >= rollback_at.date():
            record.status = "censored"
            record.outcome = "insufficient_data"
            record.comparison_start = comparison_start
            record.comparison_end = min(comparison_end, rollback_at.date())
            continue
        if comparison_end > available_end:
            record.status = "waiting"
            record.outcome = "insufficient_data"
            continue
        current = await _metric_window(
            db,
            site_id=record.site_id,
            start=comparison_start,
            end=comparison_end,
            query=record.target_query,
            target_url=record.target_url,
        )
        if not bool((record.baseline_metrics or {}).get("window_synced")) or not bool(
            current.get("window_synced")
        ):
            record.status = (
                "baseline_pending"
                if not bool((record.baseline_metrics or {}).get("window_synced"))
                else "waiting"
            )
            record.outcome = "insufficient_data"
            continue
        outcome, delta, confidence = classify_action_outcome(record.baseline_metrics, current)
        record.status = "measured"
        record.outcome = outcome
        record.comparison_start = comparison_start
        record.comparison_end = comparison_end
        record.comparison_metrics = current
        record.delta = delta
        record.confidence_score = confidence
        record.measured_at = _now()
    await db.flush()
    return records
