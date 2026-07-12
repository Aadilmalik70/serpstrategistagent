import json
import uuid

import httpx
import pytest

from app.config import get_settings
from app.services.ai_gateway import request_ai
from app.services.serpapi_service import search_serp


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "expected_path", "input_kwargs"),
    [
        (
            "chat_completions",
            "/v1/chat/completions",
            {"messages": [{"role": "user", "content": "Hello"}]},
        ),
        (
            "messages",
            "/v1/messages",
            {"messages": [{"role": "user", "content": "Hello"}]},
        ),
        (
            "responses",
            "/v1/responses",
            {"input_text": "Hello"},
        ),
    ],
)
async def test_ai_gateway_contracts_use_only_server_secret(
    monkeypatch, endpoint, expected_path, input_kwargs
):
    secret = "server-only-ai-key"
    monkeypatch.setenv("AI_GATEWAY_API_KEY", secret)
    monkeypatch.setenv("AI_GATEWAY_BASE_URL", "https://api.17.wtf/v1")
    get_settings.cache_clear()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == expected_path
        payload = json.loads(request.content)
        assert payload["model"] == "posiden/deepseek-v4-flash"
        if endpoint == "messages":
            assert request.headers["x-api-key"] == secret
            assert request.headers["anthropic-version"] == "2023-06-01"
        else:
            assert request.headers["authorization"] == f"Bearer {secret}"
        return httpx.Response(200, json={"id": "result", "usage": {"total_tokens": 3}})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.17.wtf/v1",
    ) as client:
        result = await request_ai(
            workspace_id=uuid.uuid4(),
            purpose="analysis",
            endpoint=endpoint,
            client=client,
            **input_kwargs,
        )

    assert result.model == "posiden/deepseek-v4-flash"
    assert result.usage == {"total_tokens": 3}
    assert secret not in repr(result)


@pytest.mark.asyncio
async def test_ai_gateway_falls_back_after_rate_limit(monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "server-only-ai-key")
    get_settings.cache_clear()
    attempted_models: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        attempted_models.append(payload["model"])
        if len(attempted_models) == 1:
            return httpx.Response(429, json={"error": "limited"})
        return httpx.Response(200, json={"id": "fallback-result"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.17.wtf/v1",
    ) as client:
        result = await request_ai(
            workspace_id=uuid.uuid4(),
            purpose="analysis",
            messages=[{"role": "user", "content": "Hello"}],
            client=client,
        )

    assert attempted_models == ["posiden/deepseek-v4-flash", "latina/gpt-5.6-terra"]
    assert result.model == "latina/gpt-5.6-terra"


@pytest.mark.asyncio
async def test_serpapi_uses_server_key_and_returns_workspace_attribution(monkeypatch):
    secret = "server-only-serp-key"
    workspace_id = uuid.uuid4()
    site_id = uuid.uuid4()
    monkeypatch.setenv("SERPAPI_API_KEY", secret)
    get_settings.cache_clear()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search.json"
        assert request.url.params["api_key"] == secret
        assert request.url.params["q"] == "SERP Strategists"
        return httpx.Response(200, json={"search_metadata": {"status": "Success"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await search_serp(
            workspace_id=workspace_id,
            site_id=site_id,
            query="SERP Strategists",
            purpose="rank_tracking",
            client=client,
        )

    assert result.workspace_id == workspace_id
    assert result.site_id == site_id
    assert result.purpose == "rank_tracking"
    assert secret not in repr(result)
