from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import uuid

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.entitlement_service import assert_usage_quota, record_usage


class SerpApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 503, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


@dataclass(frozen=True)
class SerpApiResult:
    data: dict[str, Any]
    workspace_id: uuid.UUID
    site_id: uuid.UUID | None
    purpose: str
    query: str
    engine: str


async def search_serp(
    *,
    workspace_id: uuid.UUID,
    query: str,
    purpose: str,
    site_id: uuid.UUID | None = None,
    engine: str = "google",
    location: str | None = None,
    google_domain: str | None = None,
    hl: str | None = None,
    gl: str | None = None,
    num: int = 10,
    client: httpx.AsyncClient | None = None,
    db: AsyncSession | None = None,
) -> SerpApiResult:
    """Run a live SERP query and meter successful usage when a DB session is supplied."""
    settings = get_settings()
    if not settings.serpapi_api_key:
        raise SerpApiError("SerpAPI is not configured", status_code=503)
    normalized_query = query.strip()
    if not normalized_query:
        raise SerpApiError("query is required", status_code=400)
    if num < 1 or num > 100:
        raise SerpApiError("num must be between 1 and 100", status_code=400)

    if db is not None:
        await assert_usage_quota(db, workspace_id=workspace_id, metric="serp_queries", requested=1)

    params: dict[str, Any] = {
        "api_key": settings.serpapi_api_key,
        "engine": engine,
        "q": normalized_query,
        "num": num,
    }
    optional = {
        "location": location,
        "google_domain": google_domain,
        "hl": hl,
        "gl": gl,
    }
    params.update({key: value for key, value in optional.items() if value})

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.serpapi_timeout_seconds, connect=5.0),
            follow_redirects=False,
        )

    try:
        try:
            response = await client.get(settings.serpapi_base_url, params=params)
        except httpx.TimeoutException as exc:
            raise SerpApiError("SerpAPI request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise SerpApiError("SerpAPI could not be reached", retryable=True) from exc

        if response.status_code in {401, 403}:
            raise SerpApiError("SerpAPI authentication failed", status_code=503)
        if response.status_code == 429:
            raise SerpApiError("SerpAPI rate limit reached", status_code=429, retryable=True)
        if response.status_code >= 500:
            raise SerpApiError("SerpAPI is temporarily unavailable", retryable=True)
        if response.status_code < 200 or response.status_code >= 300:
            raise SerpApiError(f"SerpAPI returned HTTP {response.status_code}", status_code=502)

        try:
            data = response.json()
        except ValueError as exc:
            raise SerpApiError("SerpAPI returned invalid JSON", status_code=502) from exc
        if not isinstance(data, dict):
            raise SerpApiError("SerpAPI returned an invalid response shape", status_code=502)
        if data.get("error"):
            raise SerpApiError("SerpAPI rejected the search request", status_code=502)

        result = SerpApiResult(
            data=data,
            workspace_id=workspace_id,
            site_id=site_id,
            purpose=purpose,
            query=normalized_query,
            engine=engine,
        )
        if db is not None:
            try:
                await record_usage(
                    db,
                    workspace_id=workspace_id,
                    site_id=site_id,
                    metric="serp_queries",
                    quantity=1,
                    purpose=purpose,
                    details={
                        "engine": engine,
                        "result_count": len(data.get("organic_results", []))
                        if isinstance(data.get("organic_results"), list)
                        else 0,
                    },
                    commit=True,
                    enforce_quota=False,
                )
            except Exception:
                await db.rollback()
                raise
        return result
    finally:
        if owns_client:
            await client.aclose()
