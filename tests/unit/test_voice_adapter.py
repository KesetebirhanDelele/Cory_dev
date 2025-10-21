# tests/unit/test_voice_adapter.py
import pytest
from app.channels.providers import voice

@pytest.mark.asyncio
async def test_voice_send_stub_mode():
    """In mock mode, returns queued and mock provider_ref."""
    result = await voice.send_voice("org-1", "enroll-123", "hello world", to="+15551234567")
    assert result["channel"] == "voice"
    assert result["status"] == "queued"
    assert result["provider_ref"].startswith("mock-voice-")

@pytest.mark.asyncio
async def test_voice_send_live_mode_success(monkeypatch):
    """Live mode returns 'sent' with call_id from mocked Synthflow API."""
    monkeypatch.setenv("CORY_LIVE_CHANNELS", "1")

    class DummyResponse:
        def json(self): return {"call_id": "call-123"}
        def raise_for_status(self): pass

    class DummyClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, *a, **kw): return DummyResponse()

    monkeypatch.setattr("app.channels.providers.voice.httpx.AsyncClient", DummyClient)
    result = await voice.send_voice("org-1", "enroll-123", "test live", to="+15551234567")
    assert result["status"] == "sent"
    assert result["provider_ref"] == "call-123"

@pytest.mark.asyncio
async def test_voice_send_error_mapping(monkeypatch):
    """HTTP errors map to correct taxonomy."""
    monkeypatch.setenv("CORY_LIVE_CHANNELS", "1")

    class DummyResponse:
        def raise_for_status(self):
            import httpx
            raise httpx.HTTPStatusError("fail", request=None, response=self)
        def json(self): return {}
        status_code = 503  # temporary failure

    class DummyClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, *a, **kw): return DummyResponse()

    monkeypatch.setattr("app.channels.providers.voice.httpx.AsyncClient", DummyClient)
    result = await voice.send_voice("org-1", "enroll-123", "error case", to="+15551234567")
    assert result["status"] in {"RATE_LIMIT", "TEMPORARY_FAILURE", "PERMANENT_FAILURE"}
