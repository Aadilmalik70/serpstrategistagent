from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import Subscription, UsageCounter, UsageEvent


PLAN_ENTITLEMENTS: dict[str, dict[str, int]] = {
    "audit": {
        "sites": 1,
        "monthly_crawl_pages": 500,
        "ai_requests": 25,
        "ai_tokens": 100_000,
        "serp_queries": 50,
        "team_members": 1,
    },
    "growth": {
        "sites": 5,
        "monthly_crawl_pages": 10_000,
        "ai_requests": 500,
        "ai_tokens": 2_000_000,
        "serp_queries": 1_000,
        "team_members": 5,
    },
    "scale": {
        "sites": 25,
        "monthly_crawl_pages": 100_000,
        "ai_requests": 5_000,
        "ai_tokens": 20_000_000,
        "serp_queries": 10_000,
        "team_members": 25,
    },
}

USAGE_METRICS = {"monthly_crawl_pages", "ai_requests", "ai_tokens", "serp_queries"}
RESOURCE_METRICS = {"sites", "team_members"}
ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing", "past_due"}


class QuotaExceededError(ValueError):
    def __init__(self, metric: str, limit: int, current: int, requested: int = 1):
        self.metric = metric
        self.limit = limit
        self.current = current
        self.requested = requested
        super().__init__(f"{metric} quota exceeded ({current}/{limit}). Upgrade the workspace plan to continue.")


@dataclass(frozen=True)
class UsagePeriod:
    start: datetime
    end: datetime


def get_plan_entitlements(plan: str) -> dict[str, int]:
    return dict(PLAN_ENTITLEMENTS.get(plan, PLAN_ENTITLEMENTS["audit"]))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def calendar_month_period(now: datetime | None = None) -> UsagePeriod:
    current = _as_utc(now or datetime.now(timezone.utc))
    start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return UsagePeriod(start=start, end=end)


async def get_or_create_subscription(db: AsyncSession, workspace_id: uuid.UUID) -> Subscription:
    subscription = await db.scalar(select(Subscription).where(Subscription.workspace_id == workspace_id))
    if subscription:
        return subscription

    subscription = Subscription(
        workspace_id=workspace_id,
        plan="audit",
        status="active",
        entitlements=get_plan_entitlements("audit"),
    )
    db.add(subscription)
    await db.flush()
    return subscription


async def get_effective_subscription(db: AsyncSession, workspace_id: uuid.UUID) -> Subscription:
    subscription = await get_or_create_subscription(db, workspace_id)
    if subscription.status not in ACTIVE_SUBSCRIPTION_STATUSES and subscription.plan != "audit":
        subscription.plan = "audit"
        subscription.entitlements = get_plan_entitlements("audit")
    elif not subscription.entitlements:
        subscription.entitlements = get_plan_entitlements(subscription.plan)
    return subscription


def effective_entitlements(subscription: Subscription) -> dict[str, int]:
    defaults = get_plan_entitlements(subscription.plan)
    overrides = subscription.entitlements or {}
    for key, value in overrides.items():
        if key in defaults and isinstance(value, int):
            defaults[key] = value
    return defaults


def subscription_period(subscription: Subscription, now: datetime | None = None) -> UsagePeriod:
    if subscription.current_period_start and subscription.current_period_end:
        return UsagePeriod(
            start=_as_utc(subscription.current_period_start),
            end=_as_utc(subscription.current_period_end),
        )
    return calendar_month_period(now)


async def get_usage_quantity(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    metric: str,
    period: UsagePeriod,
) -> int:
    quantity = await db.scalar(
        select(UsageCounter.quantity).where(
            UsageCounter.workspace_id == workspace_id,
            UsageCounter.metric == metric,
            UsageCounter.period_start == period.start,
            UsageCounter.period_end == period.end,
        )
    )
    return int(quantity or 0)


async def assert_usage_quota(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    metric: str,
    requested: int = 1,
) -> tuple[Subscription, UsagePeriod, int]:
    if metric not in USAGE_METRICS:
        raise ValueError(f"Unsupported usage metric: {metric}")
    if requested < 1:
        raise ValueError("requested usage must be positive")

    subscription = await get_effective_subscription(db, workspace_id)
    entitlements = effective_entitlements(subscription)
    limit = int(entitlements[metric])
    period = subscription_period(subscription)
    current = await get_usage_quantity(db, workspace_id=workspace_id, metric=metric, period=period)
    if limit >= 0 and current + requested > limit:
        raise QuotaExceededError(metric, limit, current, requested)
    return subscription, period, current


async def assert_resource_quota(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    metric: str,
    current: int,
    requested: int = 1,
) -> Subscription:
    if metric not in RESOURCE_METRICS:
        raise ValueError(f"Unsupported resource metric: {metric}")
    subscription = await get_effective_subscription(db, workspace_id)
    limit = int(effective_entitlements(subscription)[metric])
    if limit >= 0 and current + requested > limit:
        raise QuotaExceededError(metric, limit, current, requested)
    return subscription


async def record_usage(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    metric: str,
    quantity: int,
    site_id: uuid.UUID | None = None,
    purpose: str = "unspecified",
    details: dict[str, Any] | None = None,
    commit: bool = True,
) -> UsageCounter:
    if metric not in USAGE_METRICS:
        raise ValueError(f"Unsupported usage metric: {metric}")
    if quantity < 1:
        raise ValueError("usage quantity must be positive")

    subscription = await get_effective_subscription(db, workspace_id)
    period = subscription_period(subscription)
    await assert_usage_quota(
        db,
        workspace_id=workspace_id,
        metric=metric,
        requested=quantity,
    )

    statement = (
        insert(UsageCounter)
        .values(
            workspace_id=workspace_id,
            metric=metric,
            quantity=quantity,
            period_start=period.start,
            period_end=period.end,
        )
        .on_conflict_do_update(
            constraint="uq_usage_workspace_metric_period",
            set_={
                "quantity": UsageCounter.quantity + quantity,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        .returning(UsageCounter)
    )
    counter = (await db.execute(statement)).scalar_one()
    db.add(
        UsageEvent(
            workspace_id=workspace_id,
            site_id=site_id,
            metric=metric,
            quantity=quantity,
            purpose=purpose[:128] or "unspecified",
            period_start=period.start,
            period_end=period.end,
            details=details,
        )
    )
    if commit:
        await db.commit()
    else:
        await db.flush()
    return counter


async def usage_snapshot(db: AsyncSession, workspace_id: uuid.UUID) -> dict[str, dict[str, int]]:
    subscription = await get_effective_subscription(db, workspace_id)
    entitlements = effective_entitlements(subscription)
    period = subscription_period(subscription)
    result: dict[str, dict[str, int]] = {}
    for metric in sorted(USAGE_METRICS):
        used = await get_usage_quantity(db, workspace_id=workspace_id, metric=metric, period=period)
        result[metric] = {"used": used, "limit": int(entitlements[metric])}
    return result
