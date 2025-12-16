# app/orchestrator/temporal/workflows/missed_call_followup.py
from __future__ import annotations

from datetime import timedelta
from typing import Optional, Dict, Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from app.orchestrator.temporal.activities.sms_send import sms_send
    from app.orchestrator.temporal.activities.nurture_enroll import nurture_enroll


# Default “silence” window after SMS #2 before auto-enrolling in Smart Nurture.
SILENCE_WINDOW_SECONDS = 600  # 10 minutes


@workflow.defn
class MissedCallFollowupWorkflow:
    """
    Missed Call Follow-up for Fall 2025 Outreach.

    Triggered when an outbound voice call (step 1: "Initial Voice Call")
    is marked as missed (no_answer / voicemail / etc.).

    Behavior:
      - wait 5s  → send SMS #1
      - wait 5s  → send SMS #2
      - wait SILENCE_WINDOW_SECONDS (e.g. 10 min) to allow SMS replies
      - then optionally enroll the lead into a nurture campaign (Smart Nurture)

    Args to run():
        phone: E.164 phone number (e.g. "+15714782790")
        enrollment_id: enrollment this call belongs to
        campaign_id: primary outreach campaign (for logging/guarding)
        nurture_campaign_id: campaign to enroll in after missed-call flow
    """

    @workflow.run
    async def run(
        self,
        phone: str,
        enrollment_id: str,
        campaign_id: Optional[str] = None,
        nurture_campaign_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        # 1️⃣ First missed-call SMS
        await workflow.sleep(timedelta(seconds=5))
        await workflow.execute_activity(
            sms_send,
            args=[
                {
                    "enrollment_id": enrollment_id,
                    "skip_guards": True,  # missed-call followup should bypass quiet hours etc.
                    "payload": {
                        "to": phone,
                        "body": (
                            "Hi, this is Cory from admissions. I just tried calling "
                            "about your interest in our programs and it went to voicemail. "
                            "You can text me here with any questions."
                        ),
                        "campaign_id": campaign_id,
                        "kind": "missed_call_1",
                    },
                }
            ],
            start_to_close_timeout=timedelta(seconds=30),
        )

        # 2️⃣ Second follow-up SMS
        await workflow.sleep(timedelta(seconds=5))
        await workflow.execute_activity(
            sms_send,
            args=[
                {
                    "enrollment_id": enrollment_id,
                    "skip_guards": True,
                    "payload": {
                        "to": phone,
                        "body": (
                            "Just following up in case now isn’t a good time to talk. "
                            "You can reply to this text when it works for you, and "
                            "I’ll also send more details by email."
                        ),
                        "campaign_id": campaign_id,
                        "kind": "missed_call_2",
                    },
                }
            ],
            start_to_close_timeout=timedelta(seconds=30),
        )

        # 3️⃣ Silence window to allow SMS replies to come in
        if nurture_campaign_id:
            await workflow.sleep(timedelta(seconds=SILENCE_WINDOW_SECONDS))

            # 4️⃣ Enroll into nurture campaign (e.g., Smart Nurture)
            await workflow.execute_activity(
                nurture_enroll,
                args=[
                    {
                        "enrollment_id": enrollment_id,
                        "campaign_id": nurture_campaign_id,
                        "campaign_type": "nurture",
                    }
                ],
                start_to_close_timeout=timedelta(seconds=60),
            )

        return {
            "done": True,
            "nurture_enrolled": bool(nurture_campaign_id),
            "phone": phone,
            "enrollment_id": enrollment_id,
            "campaign_id": campaign_id,
            "silence_window_seconds": SILENCE_WINDOW_SECONDS
            if nurture_campaign_id
            else 0,
        }
