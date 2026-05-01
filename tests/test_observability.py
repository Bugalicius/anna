from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_service_status():
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"ok", "degraded"}
    assert "redis" in payload["services"]
    assert "postgres" in payload["services"]
    assert payload["version"]
    assert payload["timestamp"]


def test_dashboard_requires_key(monkeypatch):
    monkeypatch.setenv("DASHBOARD_KEY", "secret")
    client = TestClient(app)

    assert client.get("/dashboard").status_code == 403
    response = client.get("/dashboard?key=secret")

    assert response.status_code == 200
    assert "Ana Dashboard" in response.text
