import json
import uuid

import httpx
import pytest

from app.config import get_settings
from app.services import ai_gateway, serpapi_service


class DummySession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_ai_gateway_checks_and_records_workspace_usage(monkeypatch) -> None:
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "server-only-ai-key")
    get_settings.cache_clear()

    quota_calls: list[dict] = []
    usage_calls: list[dict] = []

    async def fake_assert_usage_quota(db, **kwargs):
        quota_calls.append(kwargs)
        return object(), object(), 0

    async def fake_record_usage(db, **kwargs):
        usage_calls.append(kwargs)
        return object()

    monkeypatch.setattr(ai_gateway, "assert_usage_quota", fake_assert_usage_quota)
    monkeypatch.setattr(ai_gateway, "record_usage", fake_record_usage)

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "metered-result",
                "model": payload["model"],
                "usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12},
            },
        )

    workspace_id = uuid.uuid4()
    site_id = uuid.uuid4()
    db = DummySession()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ai_gateway.request_ai(
            workspace_id=workspace_id,
            site_id=site_id,
            purpose="content_brief",
            messages=[{"role": "user", "content": "Create a brief"}],
            client=client,
            db=db,  # type: ignore[arg-type]
        )

    assert result.usage["total_tokens"] == 12
    assert [call["metric"] for call in quota_calls] == ["ai_requests", "ai_tokens"]
    assert [(call["metric"], call["quantity"]) for call in usage_calls] == [
        ("ai_requests", 1),
        ("ai_tokens", 12),
    ]
    assert all(call["workspace_id"] == workspace_id for call in usage_calls)
    assert all(call["site_id"] == site_id for call in usage_calls)
    assert all(call["purpose"] == "content_brief" for call in usage_calls)
    assert db.commits == 1
    assert db.rollbacks == 0


@pytest.mark.asyncio
async def test_serpapi_checks_and_records_workspace_usage(monkeypatch) -> None:
    monkeypatch.setenv("SERPAPI_API_KEY", "server-only-serp-key")
    get_settings.cache_clear()

    quota_calls: list[dict] = []
    usage_calls: list[dict] = []

    async def fake_assert_usage_quota(db, **kwargs):
        quota_calls.append(kwargs)
        return object(), object(), 0

    async def fake_record_usage(db, **kwargs):
        usage_calls.append(kwargs)
        return object()

    monkeypatch.setattr(serpapi_service, "assert_usage_quota", fake_assert_usage_quota)
    monkeypatch.setattr(serpapi_service, "record_usage", fake_record_usage)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "search_metadata": {"status": "Success"},
                "organic_results": [{"position": 1}, {"position": 2}],
            },
        )

    workspace_id = uuid.uuid4()
    site_id = uuid.uuid4()
    db = DummySession()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await serpapi_service.search_serp(
            workspace_id=workspace_id,
            site_id=site_id,
            purpose="rank_tracking",
            query="SERP Strategists",
            client=client,
            db=db,  # type: ignore[arg-type]
        )

    assert result.data["search_metadata"]["status"] == "Success"
    assert [call["metric"] for call in quota_calls] == ["serp_queries"]
    assert len(usage_calls) == 1
    assert usage_calls[0]["metric"] == "serp_queries"
    assert usage_calls[0]["quantity"] == 1
    assert usage_calls[0]["workspace_id"] == workspace_id
    assert usage_calls[0]["site_id"] == site_id
    assert usage_calls[0]["purpose"] == "rank_tracking"
    assert usage_calls[0]["details"]["result_count"] == 2
    assert db.commits == 0
    assert db.rollbacks == 0
