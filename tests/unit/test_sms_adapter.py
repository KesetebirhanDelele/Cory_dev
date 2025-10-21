# tests/unit/test_sms_adapter.py
import pytest
import uuid
import asyncio
from app.channels.providers import sms


@pytest.mark.asyncio
async def test_sms_send_stub_mode(monkeypatch):
    """Stub mode (CORY_LIVE_CHANNELS=0): returns fake provider_ref and queued status."""
    monkeypatch.setenv("CORY_LIVE_CHANNELS", "0")

    result = await sms.send_sms("org-1", "enroll-123", "hello world", to="+15551234567")

    assert result["channel"] == "sms"
    assert result["enrollment_id"] == "enroll-123"
    assert result["status"] == "queued"
    assert result["provider_ref"].startswith("stub-sms-")


@pytest.mark.asyncio
async def test_sms_send_live_mode_success(monkeypatch):
    """Live mode (CORY_LIVE_CHANNELS=1): mocked SlickText response with message_id."""
    monkeypatch.setenv("CORY_LIVE_CHANNELS", "1")

    class DummyResponse:
        def json(self): return {"message_id": "msg-123"}
        def raise_for_status(self): pass

    class DummyClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, *a, **kw): return DummyResponse()

    monkeypatch.setattr("app.channels.providers.sms.httpx.AsyncClient", DummyClient)

    result = await sms.send_sms("org-1", "enroll-123", "live test", to="+15551234567")

    assert result["status"] == "sent"
    assert result["provider_ref"] == "msg-123"
    assert result["channel"] == "sms"


@pytest.mark.asyncio
async def test_sms_send_error_mapping(monkeypatch):
    """HTTP error should map to Cory taxonomy."""
    monkeypatch.setenv("CORY_LIVE_CHANNELS", "1")

    class DummyResponse:
        def raise_for_status(self):
            import httpx
            raise httpx.HTTPStatusError("fail", request=None, response=self)
        def json(self): return {}
        status_code = 429  # rate limit

    class DummyClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, *a, **kw): return DummyResponse()

    monkeypatch.setattr("app.channels.providers.sms.httpx.AsyncClient", DummyClient)

    result = await sms.send_sms("org-1", "enroll-123", "error case", to="+15551234567")

    assert result["status"] in {"RATE_LIMIT", "TEMPORARY_FAILURE", "PERMANENT_FAILURE"}
    assert result["channel"] == "sms"
