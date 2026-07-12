from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.google_data_connection import GoogleDataConnection
from app.services.google_data_service import GoogleDataServiceError, _access_token


def _number(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


async def sync_google_baseline(
    db: AsyncSession,
    connection: GoogleDataConnection,
) -> GoogleDataConnection:
    if connection.status not in {"connected", "configured"}:
        raise GoogleDataServiceError("Connect Google data before synchronizing", 409)
    if not connection.gsc_property and not connection.ga4_property_id:
        raise GoogleDataServiceError("Select a Search Console or GA4 property first", 409)

    settings = get_settings()
    token = await _access_token(db, connection)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=27)
    summary: dict[str, object] = {
        "period": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
    }
    failures: list[str] = []

    async with httpx.AsyncClient(
        timeout=settings.google_integration_timeout_seconds,
        follow_redirects=False,
    ) as client:
        if connection.gsc_property:
            property_path = quote(connection.gsc_property, safe="")
            response = await client.post(
                f"{settings.google_search_console_api_url}/sites/{property_path}/searchAnalytics/query",
                headers=headers,
                json={
                    "startDate": start_date.isoformat(),
                    "endDate": end_date.isoformat(),
                    "rowLimit": 1,
                },
            )
            if response.status_code < 300:
                rows = response.json().get("rows", [])
                row = rows[0] if rows else {}
                summary["gsc"] = {
                    "property": connection.gsc_property,
                    "clicks": _number(row.get("clicks")),
                    "impressions": _number(row.get("impressions")),
                    "ctr": _number(row.get("ctr")),
                    "position": _number(row.get("position")),
                }
            else:
                failures.append(f"Search Console returned HTTP {response.status_code}")

        if connection.ga4_property_id:
            response = await client.post(
                f"https://analyticsdata.googleapis.com/v1beta/properties/{connection.ga4_property_id}:runReport",
                headers=headers,
                json={
                    "dateRanges": [{"startDate": "28daysAgo", "endDate": "yesterday"}],
                    "metrics": [
                        {"name": "sessions"},
                        {"name": "activeUsers"},
                        {"name": "keyEvents"},
                    ],
                    "limit": 1,
                },
            )
            if response.status_code < 300:
                rows = response.json().get("rows", [])
                values = rows[0].get("metricValues", []) if rows else []
                summary["ga4"] = {
                    "property_id": connection.ga4_property_id,
                    "property_name": connection.ga4_property_name,
                    "sessions": _number(values[0].get("value")) if len(values) > 0 else 0,
                    "active_users": _number(values[1].get("value")) if len(values) > 1 else 0,
                    "key_events": _number(values[2].get("value")) if len(values) > 2 else 0,
                }
            else:
                failures.append(f"Google Analytics returned HTTP {response.status_code}")

    now = datetime.now(timezone.utc)
    successful_sources = int("gsc" in summary) + int("ga4" in summary)
    requested_sources = int(bool(connection.gsc_property)) + int(bool(connection.ga4_property_id))
    if successful_sources == requested_sources:
        connection.baseline_status = "ready"
        connection.last_error = None
    elif successful_sources:
        connection.baseline_status = "partial"
        connection.last_error = "; ".join(failures)[:500]
    else:
        connection.baseline_status = "failed"
        connection.last_error = "; ".join(failures)[:500] or "Google baseline synchronization failed"

    connection.baseline_summary = summary
    connection.last_synced_at = now
    await db.commit()
    await db.refresh(connection)
    return connection
