# app/orchestrator/temporal/workflows/book_appointment_workflow.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any

from temporalio import workflow, activity

from app.agents.appointment_scheduler_agent import AppointmentSchedulerAgent


# ===============================================================
# Workflow Input Model
# ===============================================================

@dataclass
class BookAppointmentInput:
    lead_id: str
    enrollment_id: str
    campaign_id: Optional[str] = None
    channel: str = "voice"
    source: str = "cory"
    notes: Optional[str] = None
    candidate_slots: Optional[list[datetime]] = None


# ===============================================================
# Activity Wrapper
# ===============================================================

@activity.defn
async def schedule_appointment_activity(payload: dict) -> dict:
    """
    Activity wrapper around AppointmentSchedulerAgent.
    Only forwards lead_id plus optional context.
    """
    agent = AppointmentSchedulerAgent()

    # Pass everything except lead_id into a context block
    lead_id = payload["lead_id"]
    context = {k: v for k, v in payload.items() if k != "lead_id"}

    # Use the correct method name:
    result = await agent.schedule(lead_id, context=context)
    return result


# ===============================================================
# Workflow Definition
# ===============================================================

@workflow.defn
class BookAppointmentWorkflow:
    """
    Ticket 5 main workflow:
    - executes AppointmentSchedulerAgent inside Temporal activity
    - stores appointment task in Supabase
    - returns that row
    """

    @workflow.run
    async def run(self, inp: BookAppointmentInput) -> Dict[str, Any]:
        payload = {
            "lead_id": inp.lead_id,
            "enrollment_id": inp.enrollment_id,
            "campaign_id": inp.campaign_id,
            "channel": inp.channel,
            "source": inp.source,
            "candidate_slots": inp.candidate_slots,
            "notes": inp.notes,
        }

        result = await workflow.execute_activity(
            schedule_appointment_activity,
            payload,
            schedule_to_close_timeout=30,
        )

        return result
