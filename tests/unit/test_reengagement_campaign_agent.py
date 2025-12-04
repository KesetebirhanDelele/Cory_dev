# tests/unit/test_reengagement_campaign_agent.py
from __future__ import annotations

from typing import Dict, Any, List

import pytest

from app.agents.reengagement_campaign_agent import ReengagementCampaignAgent


class DummyRepo:
    """
    Lightweight in-memory repo so we don't hit real Supabase in unit tests.
    """

    def __init__(self) -> None:
        self.steps: List[Dict[str, Any]] = []
        self.scheduled: List[Dict[str, Any]] = []

    # Ticket 8 helpers used by the agent
    async def get_reengagement_steps(self, campaign_id: str) -> List[Dict[str, Any]]:
        # In tests we just return whatever the test stuffed into .steps
        return self.steps

    async def schedule_reengagement_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Record what was scheduled so tests can assert on it
        self.scheduled.append(payload)
        return payload


@pytest.mark.asyncio
async def test_run_campaign_no_steps(monkeypatch):
    """
    If the repo returns no reengagement steps, the agent should
    return status='no_steps' and not schedule anything.
    """
    dummy_repo = DummyRepo()

    # Patch SupabaseRepo inside the agent module to return our dummy instance
    monkeypatch.setattr(
        "app.agents.reengagement_campaign_agent.SupabaseRepo",
        lambda: dummy_repo,
    )

    agent = ReengagementCampaignAgent()

    result = await agent.run_campaign(
        lead_id="lead-1",
        campaign_id="camp-1",
    )

    assert result["status"] == "no_steps"
    assert dummy_repo.scheduled == []


@pytest.mark.asyncio
async def test_run_campaign_schedules_all_steps(monkeypatch):
    """
    When the repo returns multiple reengagement steps, the agent
    should schedule all of them via schedule_reengagement_message.
    """
    dummy_repo = DummyRepo()
    dummy_repo.steps = [
        {"id": "step-1", "template_id": "tmpl-1", "delay_minutes": 0},
        {"id": "step-2", "template_id": "tmpl-2", "delay_minutes": 60},
        {"id": "step-3", "template_id": "tmpl-3"},  # relies on default delay
    ]

    monkeypatch.setattr(
        "app.agents.reengagement_campaign_agent.SupabaseRepo",
        lambda: dummy_repo,
    )

    agent = ReengagementCampaignAgent()
    ctx = {"reason": "no_response_30_days"}

    result = await agent.run_campaign(
        lead_id="lead-123",
        campaign_id="camp-xyz",
        context=ctx,
    )

    # High-level result
    assert result["status"] == "ok"
    assert result["steps_scheduled"] == len(dummy_repo.steps)
    assert len(dummy_repo.scheduled) == len(dummy_repo.steps)

    # Each scheduled payload should have the right shape
    for original_step, scheduled in zip(dummy_repo.steps, dummy_repo.scheduled):
        assert scheduled["lead_id"] == "lead-123"
        assert scheduled["campaign_id"] == "camp-xyz"
        assert scheduled["step_id"] == original_step["id"]
        assert scheduled["template_id"] == original_step["template_id"]
        assert scheduled["context"] == ctx

        # scheduled_for should be an ISO-8601 string
        assert "scheduled_for" in scheduled
        assert isinstance(scheduled["scheduled_for"], str)
        assert "T" in scheduled["scheduled_for"]  # crude but enough for unit test
