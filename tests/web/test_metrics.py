# tests/web/test_metrics.py
from fastapi.testclient import TestClient
from app.web.server import app

client = TestClient(app)


def test_metrics_endpoint():
    """Verify that /metrics is available and returns Prometheus data."""
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "webhook_total" in r.text


def test_readyz_endpoint():
    """Verify that /readyz returns ready=200."""
    r = client.get("/readyz")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ready"
