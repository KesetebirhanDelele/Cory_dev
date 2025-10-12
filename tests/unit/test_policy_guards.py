import pytest
from datetime import datetime, timedelta, timezone
from app.policy.guards import pre_send_decision, evaluate_policy_guards, PolicyDenied


def test_pre_send_allows_when_clear():
    """All policy knobs satisfied → should allow send."""
    enrollment = {"consent": True, "labels": []}
    step = {"channel": "sms"}
    policy = {"quiet_hours": True, "quiet_start": "21:00", "quiet_end": "08:00"}
    context = {"now": "2025-05-10T12:00:00Z", "sent_count_last_24h": 0}

    verdict = pre_send_decision(enrollment=enrollment, step=step, policy=policy, context=context)
    assert verdict["allow"] is True


def test_pre_send_blocks_quiet_hours():
    """Sending during quiet hours must return allow=False."""
    enrollment = {"consent": True}
    step = {"channel": "sms"}
    policy = {"quiet_hours": True, "quiet_start": "21:00", "quiet_end": "08:00"}
    # 03:00 UTC is within 21:00–08:00 window
    context = {"now": "2025-05-10T03:00:00Z", "sent_count_last_24h": 0}

    verdict = pre_send_decision(enrollment=enrollment, step=step, policy=policy, context=context)
    assert verdict["allow"] is False
    assert verdict["reason"] == "quiet_hours"
    assert "schedule_after" in verdict["next_hint"]


def test_pre_send_blocks_no_consent():
    """Missing consent should deny send."""
    enrollment = {"consent": False}
    step = {"channel": "email"}
    policy = {}
    context = {"now": "2025-05-10T12:00:00Z"}

    verdict = pre_send_decision(enrollment=enrollment, step=step, policy=policy, context=context)
    assert verdict["allow"] is False
    assert verdict["reason"] == "no_consent"


def test_pre_send_blocks_frequency_cap():
    """Exceeded frequency cap should deny send."""
    enrollment = {"consent": True}
    step = {"channel": "voice"}
    policy = {"frequency_cap_per_24h": 3}
    context = {"now": "2025-05-10T12:00:00Z", "sent_count_last_24h": 3}

    verdict = pre_send_decision(enrollment=enrollment, step=step, policy=policy, context=context)
    assert verdict["allow"] is False
    assert verdict["reason"] == "freq_cap"


@pytest.mark.asyncio
async def test_evaluate_policy_guards_pass(monkeypatch):
    """Async wrapper should pass when all conditions satisfied."""
    async def fake_query(q, lead_id, ch): return [{"cnt": 0}]
    async_db = type("FakeDB", (), {"execute_query": fake_query})()

    lead = {"id": "L1", "metadata": {"communication_consent": {"accepted_terms": True}}}
    org = {"timezone": "America/New_York", "policy": {}}
    allowed, reason = await evaluate_policy_guards(async_db, lead, org, "sms")

    assert allowed is True
    assert reason == "allowed"


@pytest.mark.asyncio
async def test_evaluate_policy_guards_blocks():
    """Async wrapper should block when frequency cap violated."""
    async def fake_query(self, q, lead_id, ch):
        return [{"cnt": 10}]

    class FakeDB:
        async def execute_query(self, q, lead_id, ch):
            return await fake_query(self, q, lead_id, ch)

    async_db = FakeDB()

    lead = {"id": "L1", "metadata": {"communication_consent": {"accepted_terms": True}}}
    org = {"policy": {"frequency_cap_per_24h": 3}}

    allowed, reason = await evaluate_policy_guards(async_db, lead, org, "sms")
    assert not allowed
    assert reason == "freq_cap"


