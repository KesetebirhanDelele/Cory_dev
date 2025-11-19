# app/agents/appointment_scheduler_agent.py
from __future__ import annotations

import logging
from datetime import datetime, UTC
from typing import Any, Dict, Optional

from app.data.supabase_repo import SupabaseRepo

log = logging.getLogger("cory.appointment.agent")
log.setLevel(logging.INFO)


class AppointmentSchedulerAgent:
    """
    Coordinates creation of human appointment / handoff tasks.

    Ticket 5 responsibilities:
    - Accept a lead_id and optional context about the campaign/enrollment
    - Call SupabaseRepo.create_appointment_task(...)
    - Return the created appointment / handoff row
    """

    def __init__(self, repo: Optional[SupabaseRepo] = None) -> None:
        # Allow dependency injection for tests
        self.repo = repo or SupabaseRepo()

    async def schedule(
        self,
        lead_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create an appointment / handoff task for a given lead.

        `context` may include:
        - enrollment_id
        - campaign_id
        - channel (voice/sms/email)
        - source (cory, synthflow, etc.)
        - candidate_slots
        - notes
        """
        log.info("📅 AppointmentSchedulerAgent creating appointment task for lead: %s", lead_id)

        # Always normalize to a dict so tests and downstream code behave predictably
        ctx: Dict[str, Any] = context or {}

        row = await self.repo.create_appointment_task(lead_id, context=ctx)

        log.info("🆕 Appointment task created")
        return row
