import pytest

from app.agents.appointment_scheduler_agent import AppointmentSchedulerAgent


class DummyRepo:
    """Fake SupabaseRepo for unit testing."""

    def __init__(self):
        self.called_with = []

    async def create_appointment_task(self, lead_id, context=None):
        self.called_with.append((lead_id, context))
        # Return a fake "row" like Supabase would
        return {
            "id": "appt-123",
            "lead_id": lead_id,
            "status": "pending",
            "context": context,
        }


@pytest.mark.asyncio
async def test_schedule_uses_repo(monkeypatch):
    dummy_repo = DummyRepo()

    # Patch SupabaseRepo inside the agent module
    monkeypatch.setattr(
        "app.agents.appointment_scheduler_agent.SupabaseRepo",
        lambda: dummy_repo,
    )

    agent = AppointmentSchedulerAgent()
    ctx = {
        "enrollment_id": "enr-1",
        "campaign_id": "camp-1",
        "channel": "voice",
        "source": "cory",
        "notes": "test",
    }

    result = await agent.schedule("lead-123", context=ctx)

    # Check repo was called correctly
    assert dummy_repo.called_with == [("lead-123", ctx)]
    # Check shape of the returned row
    assert result["id"] == "appt-123"
    assert result["lead_id"] == "lead-123"
    assert result["status"] == "pending"


@pytest.mark.asyncio
async def test_schedule_allows_missing_context(monkeypatch):
    dummy_repo = DummyRepo()

    monkeypatch.setattr(
        "app.agents.appointment_scheduler_agent.SupabaseRepo",
        lambda: dummy_repo,
    )

    agent = AppointmentSchedulerAgent()
    result = await agent.schedule("lead-xyz")

    # Context should default to {}
    assert dummy_repo.called_with == [("lead-xyz", {})]
    assert result["lead_id"] == "lead-xyz"
