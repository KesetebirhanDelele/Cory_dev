# tests/web/test_health.py
from fastapi.testclient import TestClient
from app.web.server import app


client = TestClient(app)


def test_healthz_status_and_request_id():
    """Ensure /healthz returns 200 and includes an X-Request-ID header."""
    response = client.get("/healthz")
    assert response.status_code == 200, "Expected /healthz to return 200 OK"

    # JSON body validation
    data = response.json()
    assert data["status"] == "ok"
    assert "timestamp" in data

    # Header validation
    request_id = response.headers.get("X-Request-Id")
    assert request_id is not None and len(request_id) > 0, "X-Request-Id header missing or empty"
