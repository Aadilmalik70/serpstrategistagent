from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import time
from typing import Any
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.billing import StripeWebhookEvent, Subscription
from app.services.entitlement_service import (
    effective_entitlements,
    get_effective_subscription,
    get_or_create_subscription,
    get_plan_entitlements,
    subscription_period,
    usage_snapshot,
)


class StripeBillingError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


def _timestamp_to_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def verify_stripe_signature(
    payload: bytes,
    signature_header: str,
    secret: str,
    *,
    tolerance_seconds: int = 300,
    now: int | None = None,
) -> None:
    if not secret:
        raise StripeBillingError("Stripe webhook is not configured", status_code=503)
    if not signature_header:
        raise StripeBillingError("Stripe signature is required", status_code=400)

    parts: dict[str, list[str]] = {}
    for item in signature_header.split(","):
        key, separator, value = item.strip().partition("=")
        if separator and key and value:
            parts.setdefault(key, []).append(value)

    timestamp_values = parts.get("t", [])
    signatures = parts.get("v1", [])
    if not timestamp_values or not signatures:
        raise StripeBillingError("Stripe signature is malformed", status_code=400)

    try:
        timestamp = int(timestamp_values[0])
    except ValueError as exc:
        raise StripeBillingError("Stripe signature timestamp is invalid", status_code=400) from exc

    current = int(time.time()) if now is None else now
    if abs(current - timestamp) > tolerance_seconds:
        raise StripeBillingError("Stripe signature timestamp is outside the allowed tolerance", status_code=400)

    signed_payload = f"{timestamp}.".encode("utf-8") + payload
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, signature) for signature in signatures):
        raise StripeBillingError("Stripe signature verification failed", status_code=400)


async def _stripe_request(
    method: str,
    path: str,
    *,
    data: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise StripeBillingError("Stripe billing is not configured")

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.stripe_timeout_seconds, connect=5.0),
            follow_redirects=False,
        )

    try:
        try:
            response = await client.request(
                method,
                f"{settings.stripe_api_base_url}/{path.lstrip('/')}",
                headers={
                    "Authorization": f"Bearer {settings.stripe_secret_key}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data=data,
            )
        except httpx.TimeoutException as exc:
            raise StripeBillingError("Stripe request timed out") from exc
        except httpx.HTTPError as exc:
            raise StripeBillingError("Stripe could not be reached") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise StripeBillingError("Stripe returned invalid JSON") from exc

        if response.status_code < 200 or response.status_code >= 300:
            message = "Stripe rejected the billing request"
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"][:300]
            mapped_status = 400 if response.status_code < 500 else 503
            raise StripeBillingError(message, status_code=mapped_status)
        if not isinstance(payload, dict):
            raise StripeBillingError("Stripe returned an invalid response shape")
        return payload
    finally:
        if owns_client:
            await client.aclose()


def price_id_for_plan(plan: str) -> str:
    settings = get_settings()
    if plan == "growth":
        price_id = settings.stripe_growth_price_id
    elif plan == "scale":
        price_id = settings.stripe_scale_price_id
    else:
        raise StripeBillingError("Checkout is available for Growth and Scale plans only", status_code=400)
    if not price_id:
        raise StripeBillingError(f"Stripe price is not configured for the {plan} plan")
    return price_id


async def ensure_stripe_customer(
    db: AsyncSession,
    *,
    subscription: Subscription,
    workspace_id: uuid.UUID,
    email: str,
    name: str | None,
    client: httpx.AsyncClient | None = None,
) -> str:
    if subscription.stripe_customer_id:
        return subscription.stripe_customer_id

    data: dict[str, Any] = {
        "email": email,
        "metadata[workspace_id]": str(workspace_id),
    }
    if name:
        data["name"] = name
    customer = await _stripe_request("POST", "customers", data=data, client=client)
    customer_id = customer.get("id")
    if not isinstance(customer_id, str) or not customer_id:
        raise StripeBillingError("Stripe did not return a customer identifier")

    subscription.stripe_customer_id = customer_id
    await db.commit()
    return customer_id


async def create_checkout_session(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    plan: str,
    email: str,
    name: str | None,
    client: httpx.AsyncClient | None = None,
) -> str:
    settings = get_settings()
    subscription = await get_or_create_subscription(db, workspace_id)
    if subscription.plan in {"growth", "scale"} and subscription.status in {"active", "trialing", "past_due"}:
        raise StripeBillingError("This workspace already has a paid subscription. Use the billing portal to change it.", status_code=409)

    price_id = price_id_for_plan(plan)
    customer_id = await ensure_stripe_customer(
        db,
        subscription=subscription,
        workspace_id=workspace_id,
        email=email,
        name=name,
        client=client,
    )
    session = await _stripe_request(
        "POST",
        "checkout/sessions",
        data={
            "mode": "subscription",
            "customer": customer_id,
            "client_reference_id": str(workspace_id),
            "success_url": f"{settings.frontend_url.rstrip('/')}/settings/billing?checkout=success",
            "cancel_url": f"{settings.frontend_url.rstrip('/')}/settings/billing?checkout=cancelled",
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": "1",
            "allow_promotion_codes": "true",
            "metadata[workspace_id]": str(workspace_id),
            "metadata[plan]": plan,
            "subscription_data[metadata][workspace_id]": str(workspace_id),
            "subscription_data[metadata][plan]": plan,
        },
        client=client,
    )
    checkout_url = session.get("url")
    if not isinstance(checkout_url, str) or not checkout_url.startswith("https://"):
        raise StripeBillingError("Stripe did not return a Checkout URL")
    return checkout_url


async def create_billing_portal_session(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    client: httpx.AsyncClient | None = None,
) -> str:
    settings = get_settings()
    subscription = await get_effective_subscription(db, workspace_id)
    if not subscription.stripe_customer_id:
        raise StripeBillingError("This workspace does not have a Stripe customer yet", status_code=409)

    session = await _stripe_request(
        "POST",
        "billing_portal/sessions",
        data={
            "customer": subscription.stripe_customer_id,
            "return_url": f"{settings.frontend_url.rstrip('/')}/settings/billing",
        },
        client=client,
    )
    portal_url = session.get("url")
    if not isinstance(portal_url, str) or not portal_url.startswith("https://"):
        raise StripeBillingError("Stripe did not return a billing portal URL")
    return portal_url


def _subscription_item(subscription_object: dict[str, Any]) -> dict[str, Any]:
    items = subscription_object.get("items")
    if not isinstance(items, dict):
        return {}
    data = items.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return {}
    return data[0]


def _subscription_price_id(subscription_object: dict[str, Any]) -> str | None:
    item = _subscription_item(subscription_object)
    price = item.get("price")
    if isinstance(price, dict) and isinstance(price.get("id"), str):
        return price["id"]
    plan = item.get("plan")
    if isinstance(plan, dict) and isinstance(plan.get("id"), str):
        return plan["id"]
    return None


def _subscription_period(subscription_object: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    item = _subscription_item(subscription_object)
    start = subscription_object.get("current_period_start") or item.get("current_period_start")
    end = subscription_object.get("current_period_end") or item.get("current_period_end")
    return _timestamp_to_datetime(start), _timestamp_to_datetime(end)


def _metadata_workspace_id(data: dict[str, Any]) -> uuid.UUID | None:
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        return None
    raw = metadata.get("workspace_id")
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


async def _find_local_subscription(
    db: AsyncSession,
    stripe_object: dict[str, Any],
) -> Subscription | None:
    workspace_id = _metadata_workspace_id(stripe_object)
    if workspace_id:
        subscription = await db.scalar(select(Subscription).where(Subscription.workspace_id == workspace_id))
        if subscription:
            return subscription

    stripe_subscription_id = stripe_object.get("id") if stripe_object.get("object") == "subscription" else stripe_object.get("subscription")
    if isinstance(stripe_subscription_id, str):
        subscription = await db.scalar(
            select(Subscription).where(Subscription.stripe_subscription_id == stripe_subscription_id)
        )
        if subscription:
            return subscription

    customer_id = stripe_object.get("customer")
    if isinstance(customer_id, str):
        return await db.scalar(select(Subscription).where(Subscription.stripe_customer_id == customer_id))
    return None


async def sync_subscription_object(
    db: AsyncSession,
    stripe_subscription: dict[str, Any],
) -> Subscription:
    local = await _find_local_subscription(db, stripe_subscription)
    workspace_id = _metadata_workspace_id(stripe_subscription)
    if local is None and workspace_id:
        local = await get_or_create_subscription(db, workspace_id)
    if local is None:
        raise StripeBillingError("Stripe subscription could not be matched to a workspace", status_code=400)

    settings = get_settings()
    price_id = _subscription_price_id(stripe_subscription)
    metadata = stripe_subscription.get("metadata")
    metadata_plan = metadata.get("plan") if isinstance(metadata, dict) else None
    plan = settings.stripe_price_plan_map.get(price_id or "") or (
        metadata_plan if metadata_plan in {"growth", "scale"} else "audit"
    )
    status_value = stripe_subscription.get("status")
    status = str(status_value) if status_value else "inactive"
    if status in {"canceled", "incomplete_expired", "unpaid"}:
        plan = "audit"

    period_start, period_end = _subscription_period(stripe_subscription)
    customer_id = stripe_subscription.get("customer")
    stripe_subscription_id = stripe_subscription.get("id")

    local.plan = plan
    local.status = status
    local.stripe_price_id = price_id
    local.stripe_customer_id = customer_id if isinstance(customer_id, str) else local.stripe_customer_id
    local.stripe_subscription_id = (
        stripe_subscription_id if isinstance(stripe_subscription_id, str) else local.stripe_subscription_id
    )
    local.current_period_start = period_start
    local.current_period_end = period_end
    local.cancel_at_period_end = bool(stripe_subscription.get("cancel_at_period_end", False))
    local.entitlements = get_plan_entitlements(plan)
    await db.flush()
    return local


async def process_stripe_event(
    db: AsyncSession,
    event: dict[str, Any],
    *,
    client: httpx.AsyncClient | None = None,
) -> bool:
    event_id = event.get("id")
    event_type = event.get("type")
    data = event.get("data")
    stripe_object = data.get("object") if isinstance(data, dict) else None
    if not isinstance(event_id, str) or not isinstance(event_type, str) or not isinstance(stripe_object, dict):
        raise StripeBillingError("Stripe event payload is invalid", status_code=400)

    existing = await db.scalar(
        select(StripeWebhookEvent.id).where(StripeWebhookEvent.stripe_event_id == event_id)
    )
    if existing:
        return False

    record = StripeWebhookEvent(
        stripe_event_id=event_id,
        event_type=event_type,
        status="processing",
    )
    db.add(record)
    await db.flush()

    try:
        if event_type == "checkout.session.completed":
            local = await _find_local_subscription(db, stripe_object)
            workspace_id = _metadata_workspace_id(stripe_object)
            if local is None and workspace_id:
                local = await get_or_create_subscription(db, workspace_id)
            if local is None:
                raise StripeBillingError("Checkout session could not be matched to a workspace", status_code=400)
            customer_id = stripe_object.get("customer")
            if isinstance(customer_id, str):
                local.stripe_customer_id = customer_id
            stripe_subscription_id = stripe_object.get("subscription")
            if isinstance(stripe_subscription_id, str):
                subscription_data = await _stripe_request(
                    "GET",
                    f"subscriptions/{stripe_subscription_id}",
                    client=client,
                )
                await sync_subscription_object(db, subscription_data)
        elif event_type in {
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        }:
            await sync_subscription_object(db, stripe_object)
        elif event_type == "invoice.payment_failed":
            local = await _find_local_subscription(db, stripe_object)
            if local:
                local.status = "past_due"
        elif event_type == "invoice.paid":
            local = await _find_local_subscription(db, stripe_object)
            if local and local.status == "past_due":
                local.status = "active"

        record.status = "processed"
        await db.commit()
        return True
    except Exception as exc:
        record.status = "failed"
        record.error = str(exc)[:500]
        await db.commit()
        raise


async def parse_and_process_webhook(
    db: AsyncSession,
    *,
    payload: bytes,
    signature_header: str,
    client: httpx.AsyncClient | None = None,
) -> bool:
    settings = get_settings()
    verify_stripe_signature(payload, signature_header, settings.stripe_webhook_secret)
    try:
        event = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise StripeBillingError("Stripe webhook body is invalid JSON", status_code=400) from exc
    if not isinstance(event, dict):
        raise StripeBillingError("Stripe webhook payload is invalid", status_code=400)
    return await process_stripe_event(db, event, client=client)


async def billing_summary(db: AsyncSession, workspace_id: uuid.UUID) -> dict[str, Any]:
    settings = get_settings()
    subscription = await get_effective_subscription(db, workspace_id)
    period = subscription_period(subscription)
    return {
        "plan": subscription.plan,
        "status": subscription.status,
        "cancel_at_period_end": subscription.cancel_at_period_end,
        "current_period_start": period.start,
        "current_period_end": period.end,
        "entitlements": effective_entitlements(subscription),
        "usage": await usage_snapshot(db, workspace_id),
        "stripe_customer": bool(subscription.stripe_customer_id),
        "stripe_configured": bool(
            settings.stripe_secret_key
            and settings.stripe_webhook_secret
            and settings.stripe_growth_price_id
            and settings.stripe_scale_price_id
        ),
    }
