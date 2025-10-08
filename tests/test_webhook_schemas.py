from app.web.schemas import WebhookEvent
from pydantic import ValidationError
import pytest

def test_valid_event():
    evt = WebhookEvent(
        organization_id="org123",
        channel="sms",
        payload={"msg": "hello"}
    )
    assert evt.channel == "sms"
    assert "msg" in evt.payload

def test_missing_required_field():
    with pytest.raises(ValidationError):
        WebhookEvent(channel="sms", payload={})
