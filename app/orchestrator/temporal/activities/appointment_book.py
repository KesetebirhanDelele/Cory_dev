# app/orchestrator/temporal/activities/appointment_book.py

"""
appointment_book.py
----------------------------------------------------------
Temporal activity wrapper around AppointmentSchedulerAgent.

Used by BookAppointmentWorkflow to:
- Normalize input payload (IDs, scheduled time, notes, source)
- Call AppointmentSchedulerAgent to create an appointment row
- Link appointment back to enrollment

For now, `scheduled_for_iso` is required or inferred as "now"
if missing/invalid. Later, you can populate it directly from
Synthflow's `appointment` block in the voice webhook payload.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from temporalio import activity

from app.agents.appointment_scheduler_agent import AppointmentSchedulerAgent


def _parse_iso_datetime(value: Optional[str]) -> datetime:
    """
    Parse an ISO8601 string into a UTC datetime.
    Fallback: return "now" UTC if parsing fails or value is None.
    """
    if not value:
        return datetime.now(timezone.utc)

    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        # Conservative fallback — log via activity logger and use now()
        activity.logger.warning("Failed to parse scheduled_for_iso=%s; defaulting to now()", value)
        return datetime.now(timezone.utc)


@activity.defn
async def book_appointment_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Temporal activity entry point.

    Args (expected keys in `payload`):
        enrollment_id: str (preferred) — PK of public.enrollment
        registration_id: Optional[str] — enrollment.registration_id
        scheduled_for_iso: Optional[str] — ISO8601 datetime string
        notes: Optional[str] — notes for appointment
        source: Optional[str] — origin label (e.g. "voice_ready_to_enroll")

    Returns:
        Dict with:
            {
              "appointment": {...},  # row from public.appointments
              "enrollment": {...},   # row from public.enrollment
            }
    """
    logger = activity.logger

    enrollment_id: Optional[str] = payload.get("enrollment_id")
    registration_id: Optional[str] = payload.get("registration_id")
    scheduled_for_iso: Optional[str] = payload.get("scheduled_for_iso")
    notes: Optional[str] = payload.get("notes")
    source: str = payload.get("source", "voice_ready_to_enroll")

    if not enrollment_id and not registration_id:
        raise ValueError("book_appointment_activity requires enrollment_id or registration_id")

    scheduled_for = _parse_iso_datetime(scheduled_for_iso)

    logger.info(
        "📅 book_appointment_activity: booking appointment | enrollment_id=%s | registration_id=%s | when=%s | source=%s",
        enrollment_id,
        registration_id,
        scheduled_for.isoformat(),
        source,
    )

    agent = AppointmentSchedulerAgent()

    result = await agent.schedule_from_enrollment(
        enrollment_id=enrollment_id,
        registration_id=registration_id,
        scheduled_for=scheduled_for,
        notes=notes,
        source=source,
    )

    logger.info(
        "✅ book_appointment_activity: appointment_id=%s linked to enrollment_id=%s",
        result.get("appointment", {}).get("id"),
        result.get("enrollment", {}).get("id"),
    )

    return result
