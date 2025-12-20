# app/orchestrator/temporal/workflows/missed_call_followup.py

from __future__ import annotations

from datetime import timedelta
from typing import Optional, Dict, Any

from temporalio import workflow
from temporalio.common import RetryPolicy

# Activities (pass-through only)
with workflow.unsafe.imports_passed_through():
    from app.orchestrator.temporal.activities.sms_send import sms_send
    from app.orchestrator.temporal.activities.voice_start import voice_start
    from app.orchestrator.temporal.activities.nurture_enroll import nurture_enroll


# --------------------------------------------------
# HARD STOP: no retries anywhere
# --------------------------------------------------
NO_RETRY = RetryPolicy(maximum_attempts=1)

# Timing (seconds)
DELAY_SMS_TO_CALL = 10
DELAY_CALL_TO_SMS = 120
DELAY_BEFORE_NURTURE = 180

# Voice activity runtime budget
VOICE_ACTIVITY_TIMEOUT = timedelta(seconds=90)


@workflow.defn
class MissedCallFollowupWorkflow:
    """
    STRICT one-pass sequence:

        SMS #1
        → Call #1
        → SMS #2
        → Call #2
        → Nurture
        → END

    Guarantees:
    - No retries
    - No looping
    - No transcript waiting
    - Voice failures do NOT fail workflow
    """

    # --------------------------------------------------
    # SAFE VOICE CALL WRAPPER
    # --------------------------------------------------
    async def safe_call(self, payload: Dict[str, Any], label: str) -> None:
        """
        Executes voice_start safely.

        - Never retries
        - Never raises
        - Never blocks workflow progress
        """
        try:
            await workflow.execute_activity(
                voice_start,
                payload,
                start_to_close_timeout=VOICE_ACTIVITY_TIMEOUT,
                retry_policy=NO_RETRY,
            )
            workflow.logger.info(f"{label} initiated", extra=payload)
        except Exception as e:
            workflow.logger.warning(
                f"{label} failed, continuing workflow",
                extra={"error": str(e), "payload": payload},
            )

    # --------------------------------------------------
    # WORKFLOW ENTRYPOINT
    # --------------------------------------------------
    @workflow.run
    async def run(
        self,
        phone: str,
        enrollment_id: str,
        campaign_id: Optional[str] = None,
        nurture_campaign_id: Optional[str] = None,
    ) -> Dict[str, Any]:

        # --------------------------------------------------
        # EXECUTION GUARD (prevents accidental replays)
        # --------------------------------------------------
        if workflow.info().attempt > 1:
            workflow.logger.warning(
                "MissedCallFollowupWorkflow already executed; skipping",
                extra={"attempt": workflow.info().attempt},
            )
            return {"done": True, "skipped": True}

        # --------------------------------------------------
        # SMS #1
        # --------------------------------------------------
        await workflow.execute_activity(
            sms_send,
            {
                "enrollment_id": enrollment_id,
                "skip_guards": True,
                "payload": {
                    "to": phone,
                    "body": (
                        "Hi, this is Cory. I just tried calling and it went to voicemail. "
                        "Feel free to text me here anytime."
                    ),
                    "campaign_id": campaign_id,
                    "kind": "missed_call_sms_1",
                },
            },
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=NO_RETRY,
        )

        await workflow.sleep(timedelta(seconds=DELAY_SMS_TO_CALL))

        # --------------------------------------------------
        # CALL #1
        # --------------------------------------------------
        await self.safe_call(
            {
                "to": phone,
                "enrollment_id": enrollment_id,
                "campaign_id": campaign_id,
                "skip_guards": True,   # ✅ IMPORTANT
            },
            label="Call #1",
        )

        await workflow.sleep(timedelta(seconds=DELAY_CALL_TO_SMS))

        # --------------------------------------------------
        # SMS #2
        # --------------------------------------------------
        await workflow.execute_activity(
            sms_send,
            {
                "enrollment_id": enrollment_id,
                "skip_guards": True,
                "payload": {
                    "to": phone,
                    "body": "Sorry we missed you again! Want us to call back soon?",
                    "campaign_id": campaign_id,
                    "kind": "missed_call_sms_2",
                },
            },
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=NO_RETRY,
        )

        await workflow.sleep(timedelta(seconds=DELAY_SMS_TO_CALL))

        # --------------------------------------------------
        # CALL #2
        # --------------------------------------------------
        await self.safe_call(
            {
                "to": phone,
                "enrollment_id": enrollment_id,
                "campaign_id": campaign_id,
                "reason": "missed_call_followup_2",
                "skip_guards": True,  # 👈 ADD THIS
            },
            label="Call #2",
        )

        # --------------------------------------------------
        # NURTURE (FINAL STEP)
        # --------------------------------------------------
        if nurture_campaign_id:
            await workflow.sleep(timedelta(seconds=DELAY_BEFORE_NURTURE))

            await workflow.execute_activity(
                nurture_enroll,
                {
                    "enrollment_id": enrollment_id,
                    "campaign_id": nurture_campaign_id,
                    "campaign_type": "nurture",
                },
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=NO_RETRY,
            )

        # --------------------------------------------------
        # DONE — HARD TERMINATION
        # --------------------------------------------------
        return {
            "done": True,
            "enrollment_id": enrollment_id,
            "phone": phone,
            "campaign_id": campaign_id,
            "nurture_campaign_id": nurture_campaign_id,
        }
