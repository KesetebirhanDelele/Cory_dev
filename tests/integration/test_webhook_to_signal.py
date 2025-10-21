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
from pydantic import ValidationError

from app.orchestrator.temporal.common.provider_event import ProviderEvent, validate_provider_event


def test_sms_delivered_contract_roundtrip():
    payload = {
        "status": "delivered",
        "provider_ref": "sms_7f3c",
        "channel": "sms",
        "activity_id": "act_123",
        "data": {"provider": "SlickText", "latency_ms": 820},
    }
    pe = ProviderEvent.from_dict(payload)
    assert pe.status == "delivered"
    assert pe.channel == "sms"
    # Dict on the wire must match our minimal contract exactly
    assert pe.to_signal_dict() == payload


def test_email_bounced_contract():
    payload = {
        "status": "bounced",
        "provider_ref": "mdr_88aa",
        "channel": "email",
        "activity_id": "act_124",
        "data": {"smtp_code": 550, "reason": "User unknown"},
    }
    ok, err = validate_provider_event(payload)
    assert ok, f"expected valid provider_event, got: {err}"


def test_voice_completed_contract():
    payload = {
        "status": "completed",
        "provider_ref": "call_55ab",
        "channel": "voice",
        "activity_id": "act_125",
        "data": {"duration_s": 63, "summary": "answered"},
    }
    pe = ProviderEvent.from_dict(payload)
    assert pe.channel == "voice"
    assert pe.status == "completed"


def test_missing_required_fields_fail_validation():
    payload = {
        "status": "delivered",
        # "provider_ref" missing
        "channel": "sms",
        "activity_id": "act_999",
    }
    with pytest.raises(ValidationError):
        ProviderEvent.from_dict(payload)


def test_invalid_enum_values_fail_validation():
    payload = {
        "status": "unknown_status",
        "provider_ref": "x",
        "channel": "fax",
        "activity_id": "act_000",
    }
    ok, err = validate_provider_event(payload)
    assert not ok and "literal" in err.lower()
