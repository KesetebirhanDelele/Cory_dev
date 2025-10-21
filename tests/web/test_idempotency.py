# tests/web/test_idempotency.py
from fastapi.testclient import TestClient
from app.web.server import app

client = TestClient(app)

def make_payload(provider_ref: str):
    return {
        "event": "lead_created",
        "channel": "webhook",
        "timestamp": "2025-10-06T12:00:00Z",
        "payload": {"provider_ref": provider_ref, "first_name": "Alice"},
    }

def test_edge_idempotency_duplicate():
    # Ensure clean state
    app.state.processed_refs.clear()

    provider_ref = "provider-abc-123"

    # First call: processed
    r1 = client.post("/webhooks/campaign/test-campaign", json=make_payload(provider_ref))
    assert r1.status_code == 200
    assert r1.json().get("status") == "received"
    assert app.state.processed_refs.count(provider_ref) == 1

    # Second call: accepted but not processed
    r2 = client.post("/webhooks/campaign/test-campaign", json=make_payload(provider_ref))
    assert r2.status_code == 200
    assert r2.json().get("status") == "duplicate"
    assert app.state.processed_refs.count(provider_ref) == 1
