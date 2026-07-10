from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "serp-strategists-api"


def test_direct_codex_execution_is_blocked() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/actions/codex/00000000-0000-0000-0000-000000000000",
            json={"task": "change production code directly"},
        )

    assert response.status_code == 410
    assert "governed" in response.json()["detail"].lower()
