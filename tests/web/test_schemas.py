# tests/web/test_schemas.py
import json
import pytest
from pydantic import ValidationError
from app.web.schemas import (
    WebhookEvent,
    EmailWebhookEvent,
    SmsWebhookEvent,
    VoiceWebhookEvent,
    normalize_webhook_event,
)

@pytest.fixture(scope="session")
def examples():
    with open("app/web/openapi_examples.json") as f:
        return json.load(f)

def test_webhook_event_valid():
    payload = {
        "event": "lead_created",
        "channel": "webhook",
        "timestamp": "2025-10-06T12:00:00Z",
        "payload": {"foo": "bar"},
    }
    model = WebhookEvent.model_validate(payload)
    assert model.event == "lead_created"
    assert model.channel == "webhook"
    assert "foo" in model.payload

@pytest.mark.parametrize("cls, key", [
    (EmailWebhookEvent, "email_event"),
    (SmsWebhookEvent, "sms_event"),
])
def test_channel_specific_models_valid(examples, cls, key):
    model = cls.model_validate(examples[key]["example"])
    assert model.channel == examples[key]["example"]["channel"]

def test_missing_required_fields():
    bad_payload = {"channel": "webhook"}  # no event/timestamp
    with pytest.raises(ValidationError):
        WebhookEvent.model_validate(bad_payload)

@pytest.mark.parametrize("key", ["webhook_event", "email_event", "sms_event"])
def test_examples_round_trip(examples, key):
    example = examples[key]["example"]
    event = normalize_webhook_event(example)
    dumped = event.model_dump()
    for field in ["event", "channel", "timestamp"]:
        assert field in dumped
