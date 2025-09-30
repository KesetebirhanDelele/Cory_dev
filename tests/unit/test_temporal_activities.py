import asyncio
import pytest

from app.orchestrator.temporal.activities.sms_send import sms_send
from app.orchestrator.temporal.activities.email_send import email_send
from app.orchestrator.temporal.activities.voice_start import voice_start

pytestmark = pytest.mark.asyncio

async def _run(coro):
    return await coro

async def _assert_shape(result, channel):
    assert result["channel"] == channel
    assert result["status"] == "queued"
    assert result["provider_ref"].startswith(f"stub-{channel}-")
    assert "request" in result

async def test_sms_stub():
    out = await _run(sms_send("enr_1", {"msg": "hi"}))
    await _assert_shape(out, "sms")

async def test_email_stub():
    out = await _run(email_send("enr_2", {"subject": "hi"}))
    await _assert_shape(out, "email")

async def test_voice_stub():
    out = await _run(voice_start("enr_3", {"script": "hello"}))
    await _assert_shape(out, "voice")
