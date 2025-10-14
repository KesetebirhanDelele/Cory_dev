# tests/integration/test_webhook_repo.py
import pytest
from fastapi.testclient import TestClient
from app.web.server import app

client = TestClient(app)

@pytest.mark.asyncio
async def test_webhook_inbound_repo(monkeypatch):
    """After 1 POST → exactly one inbound event row; duplicate POST → still one row."""

    inserted = []

    async def fake_log_inbound(provider_ref, status, raw_payload):
        inserted.append(provider_ref)
        return {"provider_ref": provider_ref, "status": status}

    # Patch Supabase repo
    monkeypatch.setattr("app.data.supabase_repo.log_inbound", fake_log_inbound)

    provider_ref = "ref-abc-123"

    payload = {
        "event": "lead_created",
        "channel": "sms",
        "timestamp": "2025-10-09T00:00:00Z",
        "payload": {
            "workflow_id": "workflow-xyz",
            "provider_ref": provider_ref,
            "message": "Hello world"
        },
        "metadata": {},
    }

    # First webhook → should insert once
    r1 = client.post("/webhooks/campaign/test-campaign", json=payload)
    assert r1.status_code == 200
    assert r1.json()["status"] == "received"
    assert len(inserted) == 1

    # Duplicate webhook → should not insert again
    r2 = client.post("/webhooks/campaign/test-campaign", json=payload)
    assert r2.status_code == 200
    assert len(inserted) == 1
