# app/orchestrator/temporal/workflows/book_appointment_workflow.py

from __future__ import annotations

"""
BookAppointmentWorkflow
----------------------------------------------------------
Temporal workflow that books a human appointment once a lead
is classified as ready_to_enroll.

Usage patterns:
- Triggered from VoiceConversationAgent when intent == "ready_to_enroll"
- Triggered from CampaignWorkflow when a step resolves to ready_to_enroll
- The actual write into public.appointments is delegated to a Temporal
  activity (book_appointment_activity) which wraps AppointmentSchedulerAgent.
"""

from datetime import timedelta
from typing import Any, Dict, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

# Import activities safely for Temporal
with workflow.unsafe.imports_passed_through():
    try:
        # You will create this activity module:
        # app/orchestrator/temporal/activities/appointment_book.py
        from app.orchestrator.temporal.activities.appointment_book import (
            book_appointment_activity,
        )
    except Exception:  # pragma: no cover - allows tests to run without this module
        book_appointment_activity = None  # type: ignore[assignment]


@workflow.defn
class BookAppointmentWorkflow:
    """
    Deterministic workflow that:
    1. Takes an enrollment_id (and optionally registration_id)
    2. Delegates to book_appointment_activity (which uses AppointmentSchedulerAgent)
    3. Returns a small summary of the created appointment

    Inputs are intentionally simple so any caller (voice, SMS, email, campaign)
    can start this workflow with just IDs and an optional scheduled time.
    """

    @workflow.run
    async def run(
        self,
        *,
        enrollment_id: str,
        registration_id: Optional[str] = None,
        # optional; if None, activity may derive from Synthflow payload
        scheduled_for_iso: Optional[str] = None,
        notes: Optional[str] = None,
        source: str = "voice_ready_to_enroll",
    ) -> Dict[str, Any]:
        """
        Args:
            enrollment_id: PK of public.enrollment
            registration_id: Optional alternate key (enrollment.registration_id)
            scheduled_for_iso: ISO8601 datetime string; if omitted, the
                activity may infer from Synthflow appointment payload.
            notes: Free-form notes (e.g. "Booked via Synthflow call X")
            source: Short label indicating origin of booking
        Returns:
            Dict with 'appointment' and 'enrollment' (mirrors activity return)
        """
        logger = workflow.logger
        logger.info(
            "📅 BookAppointmentWorkflow starting | enrollment_id=%s | registration_id=%s | source=%s",
            enrollment_id,
            registration_id,
            source,
        )

        if book_appointment_activity is None:
            # Defensive guard in case activities module is missing in some env
            raise RuntimeError(
                "book_appointment_activity is not available. "
                "Ensure app.orchestrator.temporal.activities.appointment_book is created and registered."
            )

        payload: Dict[str, Any] = {
            "enrollment_id": enrollment_id,
            "registration_id": registration_id,
            "scheduled_for_iso": scheduled_for_iso,
            "notes": notes,
            "source": source,
        }

        # Run appointment booking as a Temporal activity
        result: Dict[str, Any] = await workflow.execute_activity(
            book_appointment_activity,
            args=[payload],
            schedule_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                backoff_coefficient=2.0,
            ),
        )

        logger.info(
            "✅ BookAppointmentWorkflow completed | enrollment_id=%s | appointment_id=%s",
            enrollment_id,
            result.get("appointment", {}).get("id"),
        )

        return result
