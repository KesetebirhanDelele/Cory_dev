# tests/integration/test_webhook_to_signal.py
import pytest
from fastapi.testclient import TestClient
from app.web.server import app

client = TestClient(app)

@pytest.mark.asyncio
async def test_webhook_to_signal_bridge(monkeypatch):
    """POST webhook → workflow receives provider_event and completes with matching final.status."""

    called = {}

    async def fake_send_temporal_signal(workflow_id: str, event_dict: dict) -> bool:
        called["workflow_id"] = workflow_id
        called["event"] = event_dict
        return True

    # Patch the Temporal bridge
    monkeypatch.setattr("app.orchestrator.temporal.signal_bridge.send_temporal_signal", fake_send_temporal_signal)

    payload = {
        "event": "lead_created",
        "channel": "sms",
        "timestamp": "2025-10-09T00:00:00Z",
        "payload": {
            "workflow_id": "workflow-123",
            "provider_ref": "ref-123",
            "message": "Hello there!"
        },
        "metadata": {},
    }

    response = client.post("/webhooks/campaign/test-campaign", json=payload)

    # ✅ Check that the webhook endpoint returned success
    assert response.status_code == 200
    assert response.json()["status"] == "received"

    # ✅ Check that Temporal bridge was called
    assert called["workflow_id"] == "workflow-123"
    assert called["event"]["event"] == "lead_created"
    assert "provider_ref" in called["event"]["payload"]
