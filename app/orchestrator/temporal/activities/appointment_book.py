# app/orchestrator/temporal/activities/appointment_book.py
from __future__ import annotations

import logging
from typing import Dict, Any

from temporalio import activity

from app.agents.appointment_scheduler_agent import AppointmentSchedulerAgent

log = logging.getLogger("cory.appointment.book")


@activity.defn(name="book_appointment")
async def book_appointment(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Temporal activity used by BookAppointmentWorkflow and the worker.

    Expects a payload like:
        {
            "lead_id": "lead-123",
            "enrollment_id": "enr-1" or None,
            "campaign_id": "camp-1" or None,
            "channel": "voice" | "email" | "sms",
            "source": "cory",
            "candidate_slots": [...optional...],
            "notes": "optional notes",
        }

    The AppointmentSchedulerAgent is responsible for turning this into an
    appointments row (or similar) in Supabase.
    """
    agent = AppointmentSchedulerAgent()

    # Be tolerant of slightly different method names on the agent.
    scheduler_fn = getattr(agent, "schedule_appointment", None) or getattr(
        agent, "schedule"
    )

    log.info("📅 [appointment_book] booking appointment with payload=%s", payload)

    try:
        result = await scheduler_fn(**payload)
        log.info("✅ [appointment_book] appointment booked: %s", result)
        return result
    except Exception as e:  # noqa: BLE001
        log.exception("❌ [appointment_book] failed to book appointment: %s", e)
        raise
