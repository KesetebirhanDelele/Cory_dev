# app/orchestrator/temporal/workflows/admissions_outreach.py

"""
AdmissionsOutreachWorkflow
----------------------------------------------------------
Simulates a timed outreach sequence for a single lead:

    call → SMS → call → email → escalation

Each step can be interrupted by an inbound reply signal.

Ticket 9 notes:
- This workflow can now consider an intent / next_action that may have
  been set upstream (e.g., from lead_campaign_steps via an orchestrator).
- If a decisive intent is present (ready_to_enroll, not_interested, etc.)
  we short-circuit the full sequence accordingly.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Dict, Any

from temporalio import workflow
from temporalio.common import RetryPolicy

# ---------------------------------------------------------------------
# ⏱️ Timing constants (kept short for tests/simulations)
# ---------------------------------------------------------------------
FIRST_CALL_TIMEOUT = timedelta(seconds=15)
SECOND_CALL_TIMEOUT = timedelta(seconds=15)
SMS_DELAY = timedelta(seconds=20)
SECOND_CALL_DELAY = timedelta(seconds=30)
EMAIL_DELAY = timedelta(seconds=40)
ESCALATION_DELAY = timedelta(seconds=10)

SMS_ACTIVITY_TIMEOUT = timedelta(seconds=10)
EMAIL_ACTIVITY_TIMEOUT = timedelta(seconds=15)
ESCALATION_ACTIVITY_TIMEOUT = timedelta(seconds=10)

# ---------------------------------------------------------------------
# 🧩 Activity imports (dev + live safe handling)
# ---------------------------------------------------------------------
with workflow.unsafe.imports_passed_through():
    # voice_start_dev is used in local/dev; in live we fall back to voice_start
    try:
        from app.orchestrator.temporal.activities.voice_start_dev import (
            voice_start,
            ACTIVE_CALLS,
        )
    except Exception:  # pragma: no cover - live mode
        from app.orchestrator.temporal.activities.voice_start import voice_start  # type: ignore

        # Fallback stub so signal handler doesn't crash in live mode
        ACTIVE_CALLS = {}  # type: ignore

    from app.orchestrator.temporal.activities.sms_send import sms_send
    from app.orchestrator.temporal.activities.email_send import email_send
    from app.orchestrator.temporal.activities.escalate_to_human import escalate_to_human


@workflow.defn
class AdmissionsOutreachWorkflow:
    """Deterministic outreach workflow for Cory Admissions."""

    def __init__(self) -> None:
        # Flag set by inbound_reply signal to gracefully stop the workflow
        self._stop_due_to_reply: bool = False

    # ------------------------------------------------------------------
    # 🎬 Main run method
    # ------------------------------------------------------------------
    @workflow.run
    async def run(self, lead: Dict[str, Any]) -> str:
        """
        Run the outreach sequence for a single lead.

        Args:
            lead: dict with at least {"name", "phone", "email"} keys.
                  For Ticket 9, the caller may also pass:
                    - "intent": one of the shared intents
                    - "next_action": follow-up hint from campaign logic

        Returns:
            One of:
            - "stopped_due_to_reply"
            - "completed"
            - "escalated"
        """
        logger = workflow.logger
        self._stop_due_to_reply = False

        name = lead.get("name", "Student")
        phone = lead.get("phone")
        email = lead.get("email")

        # Ticket 9: optional upstream routing hints
        intent = lead.get("intent")
        next_action = lead.get("next_action")

        logger.info(
            "🎓 Starting Admissions Outreach Workflow for %s (intent=%s, next_action=%s)",
            name,
            intent,
            next_action,
        )

        # ------------------------------------------------------------------
        # 🔀 Ticket 9: simple early branching based on existing intent
        # ------------------------------------------------------------------
        # If upstream logic (e.g. ConversationalResponseAgent + DB) has
        # already classified this lead, we can short-circuit the outreach.
        if intent == "not_interested":
            logger.info(
                "🚫 Lead %s already classified as not_interested, skipping outreach.",
                name,
            )
            return "stopped_due_to_reply"

        if intent == "ready_to_enroll":
            logger.info(
                "✅ Lead %s already ready_to_enroll, letting appointment flows handle it.",
                name,
            )
            # In the broader system, BookAppointmentWorkflow / callback flows
            # would be triggered by the orchestrator based on this intent.
            return "completed"

        # Other intents (interested_but_not_ready, unsure_or_declined,
        # callback_requested, voicemail, unclassified) fall through to the
        # normal outreach pattern for now.

        # 1️⃣ First phone call
        call_result_1 = await workflow.execute_activity(
            voice_start,
            args=[{"to": phone, "attempt": 1, "campaign_id": "mock"}],
            schedule_to_close_timeout=FIRST_CALL_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        logger.info("📞 First call result: %s", call_result_1)

        # Stop early if replied during call
        if self._stop_due_to_reply:
            logger.info("🛑 Workflow stopped due to student reply during first call.")
            return "stopped_due_to_reply"

        # 2️⃣ Wait → send SMS
        await workflow.sleep(SMS_DELAY)
        if self._stop_due_to_reply:
            logger.info("🛑 Workflow stopped before SMS due to student reply.")
            return "stopped_due_to_reply"

        sms_result = await workflow.execute_activity(
            sms_send,
            args=[phone, "Hi! This is Cory Admissions. We’d love to chat when you’re free."],
            schedule_to_close_timeout=SMS_ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        logger.info("💬 SMS result: %s", sms_result)

        # 3️⃣ Wait → second call
        await workflow.sleep(SECOND_CALL_DELAY)
        if self._stop_due_to_reply:
            logger.info("🛑 Workflow stopped before second call due to student reply.")
            return "stopped_due_to_reply"

        call_result_2 = await workflow.execute_activity(
            voice_start,
            args=[{"to": phone, "attempt": 2, "campaign_id": "mock"}],
            schedule_to_close_timeout=SECOND_CALL_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        logger.info("📞 Second call result: %s", call_result_2)

        if call_result_2.get("status") == "answered" or self._stop_due_to_reply:
            logger.info("✅ Lead answered or replied — ending sequence.")
            return "completed"

        # 4️⃣ Wait → email fallback
        await workflow.sleep(EMAIL_DELAY)
        if self._stop_due_to_reply:
            logger.info("🛑 Workflow stopped before email due to student reply.")
            return "stopped_due_to_reply"

        email_result = await workflow.execute_activity(
            email_send,
            args=[
                email,
                "We’d love to help you explore your program options",
                (
                    "Hi! This is Cory Admissions — just following up to see if you’re "
                    "still interested in applying."
                ),
            ],
            schedule_to_close_timeout=EMAIL_ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        logger.info("📧 Email result: %s", email_result)

        # 5️⃣ Wait → escalate to human advisor
        await workflow.sleep(ESCALATION_DELAY)
        if self._stop_due_to_reply:
            logger.info("🛑 Workflow stopped before escalation due to student reply.")
            return "stopped_due_to_reply"

        escalation_result = await workflow.execute_activity(
            escalate_to_human,
            args=[lead],
            schedule_to_close_timeout=ESCALATION_ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        logger.info("🧍 Escalation result: %s", escalation_result)

        logger.info("🚀 Outreach sequence completed with escalation.")
        return "escalated"

    # ------------------------------------------------------------------
    # 🧠 Signal handler for live responses
    # ------------------------------------------------------------------
    @workflow.signal
    async def inbound_reply(self, channel: str, message: str) -> None:
        """Handle inbound student replies (voice/SMS/etc.)."""
        workflow.logger.info("⚠️ Inbound reply via %s: %s", channel, message)

        if channel == "voice":
            # In dev mode, voice_start_dev exposes ACTIVE_CALLS dict; we
            # mark active calls as "answered" so the activity can return.
            try:
                for num in list(ACTIVE_CALLS.keys()):  # type: ignore[name-defined]
                    ACTIVE_CALLS[num] = "answered"  # type: ignore[index]
                workflow.logger.info("☎️ Active call marked as answered via signal.")
            except Exception as e:  # pragma: no cover - best effort
                workflow.logger.warning("⚠️ Could not update ACTIVE_CALLS: %s", e)

        # Mark the workflow for graceful stop on the next checkpoint
        self._stop_due_to_reply = True
        workflow.logger.info("✅ Student reply received — workflow will stop soon.")
