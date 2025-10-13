import pytest
from app.orchestrator.temporal.workflows.campaign import CampaignWorkflow

import os
os.environ["ENABLE_GUARDS"] = "0"

@pytest.mark.asyncio
async def test_multistep_three_phase(monkeypatch):
    """3-step campaign executes sequentially and branches on failure."""

    fake_result = {"status": "sent"}
    async def fake_email_send(*a, **kw): return fake_result
    async def fake_sms_send(*a, **kw): return fake_result
    async def fake_voice_start(*a, **kw): return fake_result

    # ✅ Patch inside workflow namespace
    monkeypatch.setattr("app.orchestrator.temporal.workflows.campaign.email_send", fake_email_send)
    monkeypatch.setattr("app.orchestrator.temporal.workflows.campaign.sms_send", fake_sms_send)
    monkeypatch.setattr("app.orchestrator.temporal.workflows.campaign.voice_start", fake_voice_start)

    # ✅ Always allow guards
    monkeypatch.setattr("app.policy.guards.pre_send_decision", lambda **kw: {"allow": True})

    steps = [
        {"action": "send_email", "channel": "email", "payload": {"to": "x"}, "wait_hours": 1},
        {"action": "send_sms", "channel": "sms", "payload": {"to": "x"}, "wait_hours": 1},
        {"action": "voice_start", "channel": "voice", "payload": {"to": "x"}, "wait_hours": 0},
    ]

    wf = CampaignWorkflow()
    result = await wf.run("CAMP123", steps)

    assert "history" in result
    assert len(result["history"]) == 3
    for entry in result["history"]:
        assert entry["attempt"]["status"] == "sent"

@pytest.mark.asyncio
async def test_multistep_branches_on_failure(monkeypatch):
    """If first step fails, workflow should jump to fallback step."""
    async def fake_email_send(*a, **kw): return {"status": "failed"}
    async def fake_sms_send(*a, **kw): return {"status": "sent"}
    async def fake_voice_start(*a, **kw): return {"status": "sent"}

    monkeypatch.setattr("app.orchestrator.temporal.activities.email_send", fake_email_send)
    monkeypatch.setattr("app.orchestrator.temporal.activities.sms_send", fake_sms_send)
    monkeypatch.setattr("app.orchestrator.temporal.activities.voice_start", fake_voice_start)

    steps = [
        {"action": "send_email", "channel": "email", "payload": {"to": "x"}, "on_failure": 2},
        {"action": "send_sms", "channel": "sms", "payload": {"to": "x"}},
        {"action": "voice_start", "channel": "voice", "payload": {"to": "x"}},
    ]

    wf = CampaignWorkflow()
    result = await wf.run("CAMP123", steps)

    # should skip directly to step 2 (index 2)
    assert len(result["history"]) == 2
    assert result["history"][-1]["action"] == "voice_start"
