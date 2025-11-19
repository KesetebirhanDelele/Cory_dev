import pytest

from app.orchestrator.temporal.workflows.book_appointment_workflow import (
    schedule_appointment_activity,
)


class DummyAgent:
    def __init__(self):
        self.calls = []

    async def schedule(self, lead_id, context=None):
        self.calls.append((lead_id, context))
        return {
            "id": "appt-999",
            "lead_id": lead_id,
            "status": "pending",
            "context": context,
        }


@pytest.mark.asyncio
async def test_schedule_appointment_activity(monkeypatch):
    dummy_agent = DummyAgent()

    # Patch the AppointmentSchedulerAgent that the activity uses
    monkeypatch.setattr(
        "app.orchestrator.temporal.workflows.book_appointment_workflow.AppointmentSchedulerAgent",
        lambda: dummy_agent,
    )

    payload = {
        "lead_id": "L-1",
        "enrollment_id": "ENR-1",
        "campaign_id": "CAMP-1",
        "channel": "voice",
        "source": "cory",
        "candidate_slots": [],
        "notes": "from test",
    }

    result = await schedule_appointment_activity(payload)

    # Agent was called exactly once
    assert dummy_agent.calls == [
        (
            "L-1",
            {
                "enrollment_id": "ENR-1",
                "campaign_id": "CAMP-1",
                "channel": "voice",
                "source": "cory",
                "candidate_slots": [],
                "notes": "from test",
            },
        )
    ]

    # Activity returns the row from the agent
    assert result["id"] == "appt-999"
    assert result["lead_id"] == "L-1"
    assert result["status"] == "pending"
