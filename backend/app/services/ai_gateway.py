from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
import uuid

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.entitlement_service import assert_usage_quota, record_usage


AIGatewayEndpoint = Literal["chat_completions", "messages", "responses"]


class AIGatewayError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 503, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


@dataclass(frozen=True)
class AIGatewayResult:
    data: dict[str, Any]
    model: str
    endpoint: AIGatewayEndpoint
    workspace_id: uuid.UUID
    site_id: uuid.UUID | None
    purpose: str
    usage: dict[str, Any]


def _model_candidates(requested_model: str | None, purpose: str) -> list[str]:
    settings = get_settings()
    if requested_model:
        primary = requested_model
    elif purpose == "reasoning":
        primary = settings.ai_reasoning_model
    else:
        primary = settings.ai_primary_model

    return list(
        dict.fromkeys(
            model
            for model in (
                primary,
                settings.ai_fallback_model,
                settings.ai_secondary_fallback_model,
            )
            if model
        )
    )


def _request_parts(
    *,
    endpoint: AIGatewayEndpoint,
    model: str,
    api_key: str,
    messages: list[dict[str, Any]] | None,
    input_text: str | None,
    max_tokens: int,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    if endpoint == "chat_completions":
        if not messages:
            raise AIGatewayError("messages are required for chat completions", status_code=400)
        return (
            "chat/completions",
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            {"model": model, "messages": messages},
        )
    if endpoint == "messages":
        if not messages:
            raise AIGatewayError("messages are required for Anthropic messages", status_code=400)
        return (
            "messages",
            {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            {"model": model, "max_tokens": max_tokens, "messages": messages},
        )
    if endpoint == "responses":
        if not input_text:
            raise AIGatewayError("input_text is required for responses", status_code=400)
        return (
            "responses",
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            {"model": model, "input": input_text},
        )
    raise AIGatewayError("Unsupported AI gateway endpoint", status_code=400)


def _usage_token_count(usage: dict[str, Any]) -> int:
    for key in ("total_tokens", "total_token_count"):
        value = usage.get(key)
        if isinstance(value, int) and value >= 0:
            return value

    total = 0
    found = False
    for key in ("input_tokens", "output_tokens", "prompt_tokens", "completion_tokens"):
        value = usage.get(key)
        if isinstance(value, int) and value >= 0:
            total += value
            found = True
    return total if found else 0


async def request_ai(
    *,
    workspace_id: uuid.UUID,
    purpose: str,
    site_id: uuid.UUID | None = None,
    endpoint: AIGatewayEndpoint = "chat_completions",
    messages: list[dict[str, Any]] | None = None,
    input_text: str | None = None,
    model: str | None = None,
    max_tokens: int = 1024,
    client: httpx.AsyncClient | None = None,
    db: AsyncSession | None = None,
) -> AIGatewayResult:
    """Call the server-managed AI gateway and meter successful usage when a DB session is supplied."""
    settings = get_settings()
    if not settings.ai_gateway_api_key:
        raise AIGatewayError("AI gateway is not configured", status_code=503)
    if max_tokens <= 0:
        raise AIGatewayError("max_tokens must be greater than zero", status_code=400)

    if db is not None:
        await assert_usage_quota(db, workspace_id=workspace_id, metric="ai_requests", requested=1)
        await assert_usage_quota(db, workspace_id=workspace_id, metric="ai_tokens", requested=1)

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.ai_gateway_timeout_seconds, connect=5.0),
            follow_redirects=False,
        )

    last_error: AIGatewayError | None = None
    try:
        for candidate in _model_candidates(model, purpose):
            path, headers, payload = _request_parts(
                endpoint=endpoint,
                model=candidate,
                api_key=settings.ai_gateway_api_key,
                messages=messages,
                input_text=input_text,
                max_tokens=max_tokens,
            )
            url = f"{settings.ai_gateway_base_url}/{path}"
            try:
                response = await client.post(url, headers=headers, json=payload)
            except httpx.TimeoutException:
                last_error = AIGatewayError("AI gateway request timed out", retryable=True)
                continue
            except httpx.HTTPError:
                last_error = AIGatewayError("AI gateway could not be reached", retryable=True)
                continue

            if response.status_code in {401, 403}:
                raise AIGatewayError("AI gateway authentication failed", status_code=503)
            if response.status_code == 429:
                last_error = AIGatewayError("AI gateway rate limit reached", status_code=429, retryable=True)
                continue
            if response.status_code >= 500:
                last_error = AIGatewayError("AI gateway is temporarily unavailable", retryable=True)
                continue
            if response.status_code < 200 or response.status_code >= 300:
                raise AIGatewayError(
                    f"AI gateway returned HTTP {response.status_code}",
                    status_code=502,
                )

            try:
                data = response.json()
            except ValueError:
                last_error = AIGatewayError("AI gateway returned invalid JSON", retryable=True)
                continue
            if not isinstance(data, dict):
                last_error = AIGatewayError("AI gateway returned an invalid response shape", retryable=True)
                continue

            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            result = AIGatewayResult(
                data=data,
                model=candidate,
                endpoint=endpoint,
                workspace_id=workspace_id,
                site_id=site_id,
                purpose=purpose,
                usage=usage,
            )
            if db is not None:
                try:
                    await record_usage(
                        db,
                        workspace_id=workspace_id,
                        site_id=site_id,
                        metric="ai_requests",
                        quantity=1,
                        purpose=purpose,
                        details={"model": candidate, "endpoint": endpoint},
                        commit=False,
                        enforce_quota=False,
                    )
                    token_count = _usage_token_count(usage)
                    if token_count > 0:
                        await record_usage(
                            db,
                            workspace_id=workspace_id,
                            site_id=site_id,
                            metric="ai_tokens",
                            quantity=token_count,
                            purpose=purpose,
                            details={"model": candidate, "endpoint": endpoint},
                            commit=False,
                            enforce_quota=False,
                        )
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
            return result
    finally:
        if owns_client:
            await client.aclose()

    raise last_error or AIGatewayError("AI gateway request failed")
