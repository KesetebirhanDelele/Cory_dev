import pytest
import app.channels.providers.email as email

@pytest.mark.asyncio
async def test_email_send_stub_mode():
    """Stub mode returns queued mock email."""
    result = await email.send_email("org-1", "enroll-1", "Hi", "Body", to="test@example.com")
    assert result["status"] == "queued"
    assert "mock-email" in result["provider_ref"]

@pytest.mark.asyncio
async def test_email_send_live_mode_success(monkeypatch):
    """Live mode returns sent."""
    monkeypatch.setenv("CORY_LIVE_CHANNELS", "1")

    class DummyResponse:
        def json(self): return [{"_id": "msg-123"}]
        def raise_for_status(self): pass

    class DummyClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, *a, **kw): return DummyResponse()

    monkeypatch.setattr("app.channels.providers.email.httpx.AsyncClient", DummyClient)
    result = await email.send_email("org-1", "enroll-2", "Live", "Body", to="real@example.com")
    assert result["status"] == "sent"
    assert result["provider_ref"] == "msg-123"

@pytest.mark.asyncio
async def test_email_send_error_mapping(monkeypatch):
    """HTTP errors map to Cory taxonomy."""
    monkeypatch.setenv("CORY_LIVE_CHANNELS", "1")

    class DummyResponse:
        status_code = 429
        def raise_for_status(self):
            import httpx
            raise httpx.HTTPStatusError("fail", request=None, response=self)
        def json(self): return {}

    class DummyClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, *a, **kw): return DummyResponse()

    monkeypatch.setattr("app.channels.providers.email.httpx.AsyncClient", DummyClient)
    result = await email.send_email("org-1", "enroll-3", "Err", "Body", to="rate@example.com")
    assert result["status"] in {"RATE_LIMIT", "TEMPORARY_FAILURE", "PERMANENT_FAILURE"}
