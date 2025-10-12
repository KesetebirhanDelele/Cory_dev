import pytest
from app.policy.guards_budget import evaluate_budget_caps

@pytest.mark.asyncio
async def test_budget_cap_blocks():
    async def fake_query(self, q, *args):
        if "SUM" in q:
            return [{"spent": 150.0}]
        return [{"cnt": 10}]

    class FakeDB:
        async def execute_query(self, q, *args):
            return await fake_query(self, q, *args)

    async_db = FakeDB()
    policy = {"budget_usd_limit": 100.0, "rate_limit_per_hour": 100}
    allowed, reason, hint = await evaluate_budget_caps(async_db, "CAMP123", "sms", policy)
    assert not allowed and reason == "budget_cap"
    assert "pause_campaign" in hint.values()

@pytest.mark.asyncio
async def test_rate_cap_blocks(monkeypatch):
    async def fake_query(self, q, *args):
        if "SUM" in q:
            return [{"spent": 50.0}]  # under budget
        return [{"cnt": 999}]  # over rate cap

    class FakeDB:
        async def execute_query(self, q, *args):
            return await fake_query(self, q, *args)

    async_db = FakeDB()
    policy = {"budget_usd_limit": 100.0, "rate_limit_per_hour": 100}

    allowed, reason, hint = await evaluate_budget_caps(async_db, "CAMP123", "sms", policy)
    assert not allowed and reason == "rate_cap"
    assert "retry_in_minutes" in hint

@pytest.mark.asyncio
async def test_caps_pass_under_limits(monkeypatch):
    async def fake_query(q, *args):
        if "SUM" in q:
            return [{"spent": 50.0}]
        return [{"cnt": 10}]
    async_db = type("FakeDB", (), {"execute_query": fake_query})()
    policy = {"budget_usd_limit": 200.0, "rate_limit_per_hour": 100}
    allowed, reason, hint = await evaluate_budget_caps(async_db, "CAMP123", "sms", policy)
    assert allowed and reason == "allowed"
