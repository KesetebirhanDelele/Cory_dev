# app/agents/appointment_scheduler_agent.py
"""
AppointmentSchedulerAgent
----------------------------------------------------------
Creates and links appointments in Supabase when a student
is ready to enroll (e.g., after a Synthflow voice call or
classified SMS/email reply).

Responsibilities:
- Look up enrollment / lead / campaign context
- Insert a row into public.appointments
- Link appointment_id back onto enrollment
- Optionally annotate the latest lead_campaign_steps row
"""

import os
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()
log = logging.getLogger("cory.appointment.agent")
log.setLevel(logging.INFO)


class AppointmentSchedulerAgent:
    """
    Thin wrapper around Supabase for booking appointments and linking
    them to an enrollment.

    Typical usage (from a workflow or webhook handler):

        agent = AppointmentSchedulerAgent()
        await agent.schedule_from_enrollment(
            enrollment_id="...",
            scheduled_for=some_datetime,
            notes="Booked via Synthflow voice call",
        )
    """

    def __init__(self) -> None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

        if not url or not key:
            raise ValueError(
                "Missing Supabase credentials (SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY)."
            )

        self.supabase: Client = create_client(url, key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def schedule_from_enrollment(
        self,
        *,
        enrollment_id: Optional[str] = None,
        registration_id: Optional[str] = None,
        scheduled_for: datetime,
        notes: Optional[str] = None,
        source: str = "synthflow_voice",
    ) -> Dict[str, Any]:
        """
        Create an appointment for the given enrollment/registration and
        link it back to public.enrollment.appointment_id.

        Either enrollment_id OR registration_id must be provided.

        Args:
            enrollment_id: Primary key of public.enrollment (preferred)
            registration_id: Alternate lookup key (enrollment.registration_id)
            scheduled_for: When the appointment will occur (UTC or naive → UTC)
            notes: Optional human-readable notes (e.g. from Synthflow)
            source: Short label describing origin of appointment
        Returns:
            dict with 'appointment' and 'enrollment' keys
        """
        if not enrollment_id and not registration_id:
            raise ValueError("Must provide either enrollment_id or registration_id")

        # Normalize datetime → UTC
        if scheduled_for.tzinfo is None:
            scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
        else:
            scheduled_for = scheduled_for.astimezone(timezone.utc)

        # 1️⃣ Lookup enrollment
        enrollment = self._get_enrollment(
            enrollment_id=enrollment_id,
            registration_id=registration_id,
        )

        # 2️⃣ Build and insert appointment row
        appointment = self._insert_appointment_row(
            enrollment=enrollment,
            scheduled_for=scheduled_for,
            notes=notes,
            source=source,
        )

        # 3️⃣ Link appointment back to enrollment
        self._link_appointment_to_enrollment(
            enrollment_id=enrollment["id"],
            appointment_id=appointment["id"],
        )

        log.info(
            "📅 Appointment booked | enrollment=%s | registration=%s | when=%s",
            enrollment["id"],
            enrollment["registration_id"],
            scheduled_for.isoformat(),
        )

        return {
            "appointment": appointment,
            "enrollment": enrollment,
        }

    # ------------------------------------------------------------------
    # Internal helpers (sync, called from async wrapper)
    # ------------------------------------------------------------------
    def _get_enrollment(
        self,
        *,
        enrollment_id: Optional[str],
        registration_id: Optional[str],
    ) -> Dict[str, Any]:
        """
        Synchronously fetch enrollment row from Supabase using either id or registration_id.
        """
        if enrollment_id:
            res = (
                self.supabase.table("enrollment")
                .select("id, registration_id, project_id, campaign_id, contact_id")
                .eq("id", enrollment_id)
                .limit(1)
                .execute()
            )
        else:
            res = (
                self.supabase.table("enrollment")
                .select("id, registration_id, project_id, campaign_id, contact_id")
                .eq("registration_id", registration_id)
                .limit(1)
                .execute()
            )

        if not res.data:
            raise ValueError(
                f"Enrollment not found for "
                f"{'id=' + enrollment_id if enrollment_id else 'registration_id=' + str(registration_id)}"
            )

        return res.data[0]

    def _insert_appointment_row(
        self,
        *,
        enrollment: Dict[str, Any],
        scheduled_for: datetime,
        notes: Optional[str],
        source: str,
    ) -> Dict[str, Any]:
        """
        Insert a record into public.appointments for the given enrollment.
        """
        payload = {
            "registration_id": enrollment.get("registration_id"),
            "lead_id": enrollment.get("contact_id"),
            "project_id": enrollment.get("project_id"),
            "campaign_id": enrollment.get("campaign_id"),
            "scheduled_for": scheduled_for.isoformat(),
            "notes": notes or f"Booked via {source}",
            "outcome": None,
        }

        res = self.supabase.table("appointments").insert(payload).execute()
        if not res.data:
            raise RuntimeError("Failed to insert appointment row in Supabase")

        return res.data[0]

    def _link_appointment_to_enrollment(
        self,
        *,
        enrollment_id: str,
        appointment_id: str,
    ) -> None:
        """
        Update public.enrollment.appointment_id to reference the new appointment.
        """
        now = datetime.now(timezone.utc).isoformat()
        self.supabase.table("enrollment").update(
            {
                "appointment_id": appointment_id,
                "updated_at": now,
            }
        ).eq("id", enrollment_id).execute()

        log.info(
            "🔗 Linked appointment %s → enrollment %s",
            appointment_id,
            enrollment_id,
        )
