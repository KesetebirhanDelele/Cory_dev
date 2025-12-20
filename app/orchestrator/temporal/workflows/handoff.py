# app/orchestrator/temporal/workflows/handoff.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import timedelta

from temporalio import workflow

from app.common.tracing import set_trace_id  # (optional for future, not required here)

with workflow.unsafe.imports_passed_through():
    from app.orchestrator.temporal.activities.handoff_create import (
        create_handoff,
        resolve_handoff_rpc,
        mark_timed_out,
    )
    from app.orchestrator.temporal.activities.appointment_book import (
        book_appointment_activity,
    )


# -------- Types --------
@dataclass
class HandoffInput:
    # Core fields
    workflow_run_id: Optional[str]
    subject: str
    channel: str
    payload: Dict[str, Any]
    timeout_seconds: int = 600
    created_by: Optional[str] = None
    assignee: Optional[str] = None
    organization_id: Optional[str] = None  # keep as Optional[str] for consistency

    # Optional context for human + routing
    lead_id: Optional[str] = None
    interaction_id: Optional[str] = None
    enrollment_id: Optional[str] = None
    registration_id: Optional[str] = None

    intent: Optional[str] = None          # e.g. "ready_to_enroll", "needs_human"
    next_action: Optional[str] = None     # e.g. "handoff_to_human"

    # For advisors / CRM
    last_message: Optional[Dict[str, Any]] = None  # snapshot of last user message (text, from, etc.)
    priority: Optional[str] = None                 # "normal" | "high"

    # Appointment / booking hints (ticket 7)
    scheduled_for_iso: Optional[str] = None        # desired time, ISO8601; may be None
    booking_notes: Optional[str] = None            # free-form notes for appointment
    appointment_source: Optional[str] = None       # e.g. "sms_handoff" or "voice_handoff"
    auto_book: bool = False                        # force booking even if intent is missing


@dataclass
class HandoffResult:
    handoff_id: str
    outcome: str                 # "resolved" | "timed_out"
    resolution_payload: Dict[str, Any]
    booking: Optional[Dict[str, Any]] = None       # appointment / booking info if auto-booked


# -------- Workflow --------
@workflow.defn
class HandoffWorkflow:
    def __init__(self) -> None:
        self._resolved: bool = False
        self._resolution_payload: Dict[str, Any] = {}
        self._handoff_id: Optional[str] = None
        self._trace_id: Optional[str] = None
        self._log = workflow.logger

    @workflow.signal(name="resolve")
    def resolve(
        self,
        resolution_payload: Optional[Dict[str, Any]] = None,
        *,
        decision: Optional[str] = None,
        by: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> None:
        payload = resolution_payload or {}
        merged = {**payload}
        if decision is not None:
            merged["decision"] = decision
        if by is not None:
            merged["by"] = by
        if trace_id:
            self._trace_id = trace_id  # capture from signal if provided

        if not self._resolved:
            self._resolved = True
            self._resolution_payload = merged
            self._log.info("Signal 'resolve' received: %s", self._resolution_payload)
        else:
            self._log.info("Signal 'resolve' received again; ignoring (already resolved).")

    @workflow.run
    async def run(self, data: HandoffInput) -> HandoffResult:
        # 🧩 extract trace_id from start headers (Temporal header values are bytes)
        start_headers = workflow.info().headers or {}
        if b"trace_id" in start_headers:
            try:
                self._trace_id = start_headers[b"trace_id"].decode("utf-8", "ignore")
            except Exception:
                self._trace_id = None

        # NEW: fallback to input payload for older SDKs
        if not self._trace_id:
            try:
                self._trace_id = (data.payload or {}).get("trace_id")
            except Exception:
                self._trace_id = None

        self._log.info(
            "HandoffWorkflow start | run_id=%s subject=%s channel=%s timeout=%ss org=%s trace=%s",
            data.workflow_run_id,
            data.subject,
            data.channel,
            data.timeout_seconds,
            data.organization_id,
            self._trace_id,
        )

        # activity headers could carry trace_id forward if you enable them later
        # act_headers = {}
        # if self._trace_id:
        #     act_headers = {b"trace_id": self._trace_id.encode("utf-8")}

        # --------------------------------------------------
        # 1️⃣ Optional: Auto-book appointment for ready/needs_human
        # --------------------------------------------------
        booking_info: Optional[Dict[str, Any]] = None

        # Determine whether we should attempt an appointment booking
        should_auto_book = (
            data.auto_book
            or (data.intent in {"ready_to_enroll", "needs_human"})
        )

        appt_enrollment_id = data.enrollment_id or (data.payload or {}).get("enrollment_id")
        appt_registration_id = data.registration_id or (data.payload or {}).get("registration_id")

        if should_auto_book and (appt_enrollment_id or appt_registration_id):
            # Pull time/notes/source from inputs or payload
            scheduled_for_iso = (
                data.scheduled_for_iso
                or (data.payload or {}).get("scheduled_for_iso")
            )
            booking_notes = (
                data.booking_notes
                or (data.payload or {}).get("booking_notes")
                or (data.payload or {}).get("notes")
            )
            source = (
                data.appointment_source
                or (data.payload or {}).get("appointment_source")
                or f"{data.channel}_handoff"
            )

            try:
                booking_result = await workflow.execute_activity(
                    book_appointment_activity,
                    {
                        "enrollment_id": appt_enrollment_id,
                        "registration_id": appt_registration_id,
                        "scheduled_for_iso": scheduled_for_iso,
                        "notes": booking_notes,
                        "source": source,
                    },
                    start_to_close_timeout=timedelta(seconds=30),
                )

                appointment = booking_result.get("appointment") or {}
                booking_info = {
                    "appointment_id": appointment.get("id"),
                    "scheduled_for": appointment.get("scheduled_for"),
                    "booking_link": appointment.get("booking_link"),
                    "source": source,
                    "raw": booking_result,
                }

                self._log.info(
                    "HandoffWorkflow: auto-booked appointment_id=%s for enrollment_id=%s",
                    booking_info["appointment_id"],
                    appt_enrollment_id,
                )
            except Exception as ex:  # noqa: BLE001
                self._log.exception(
                    "HandoffWorkflow: failed to auto-book appointment for enrollment_id=%s: %s",
                    appt_enrollment_id,
                    ex,
                )
                booking_info = None

        # --------------------------------------------------
        # 2️⃣ Create handoff row in Supabase
        # --------------------------------------------------
        self._handoff_id = await workflow.execute_activity(
            create_handoff,
            {
                "workflow_run_id": data.workflow_run_id,
                "subject": data.subject,
                "channel": data.channel,
                "payload": {
                    **(data.payload or {}),
                    "trace_id": self._trace_id,
                    "booking": booking_info,
                    "intent": data.intent,
                    "next_action": data.next_action,
                },
                "timeout_seconds": data.timeout_seconds,
                "created_by": data.created_by,
                "assignee": data.assignee,
                "organization_id": data.organization_id,
                "lead_id": data.lead_id,
                "interaction_id": data.interaction_id,
                "enrollment_id": appt_enrollment_id,
                "intent": data.intent,
                "next_action": data.next_action,
                "last_message": data.last_message,
                "priority": data.priority,
                "booking": booking_info,
            },
            start_to_close_timeout=timedelta(seconds=20),
            # headers=act_headers,
        )
        self._log.info("Created handoff_id=%s", self._handoff_id)

        # --------------------------------------------------
        # 3️⃣ Wait for human to resolve, or timeout
        # --------------------------------------------------
        timeout_td = timedelta(seconds=data.timeout_seconds)
        self._log.info("Waiting for resolve up to %s", timeout_td)

        resolved = await workflow.wait_condition(
            lambda: self._resolved,
            timeout=timeout_td,
        )
        if not resolved and self._resolved:
            # defensive guard (kept from your working version)
            resolved = True

        if resolved:
            self._log.info("Resolved before timeout; applying resolution via RPC")
            await workflow.execute_activity(
                resolve_handoff_rpc,
                {
                    "handoff_id": self._handoff_id,
                    "resolution_payload": {
                        **self._resolution_payload,
                        "trace_id": self._trace_id,
                        "booking": booking_info,
                    },
                },
                start_to_close_timeout=timedelta(seconds=20),
                # headers=act_headers,
            )
            outcome = "resolved"
        else:
            self._log.info(
                "Timed out after %s seconds; marking as timed_out",
                data.timeout_seconds,
            )
            await workflow.execute_activity(
                mark_timed_out,
                {"handoff_id": self._handoff_id, "trace_id": self._trace_id},
                start_to_close_timeout=timedelta(seconds=20),
                # headers=act_headers,
            )
            outcome = "timed_out"

        return HandoffResult(
            handoff_id=self._handoff_id or "",
            outcome=outcome,
            resolution_payload=self._resolution_payload,
            booking=booking_info,
        )
