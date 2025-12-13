# app/orchestrator/temporal/workflows/missed_call_followup.py

from __future__ import annotations

from datetime import timedelta
from typing import Optional, Dict, Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from app.orchestrator.temporal.activities.sms_send import sms_send
    from app.orchestrator.temporal.activities.nurture_enroll import nurture_enroll


@workflow.defn
class MissedCallFollowupWorkflow:
    """
    Triggered when an outbound voice call is marked as `no_answer` / `voicemail`.

    Behavior:
      - wait 30s → send SMS #1
      - wait 25s → send SMS #2
      - then enroll the lead into a nurture campaign.

    Args to run():
        phone: E.164 phone number
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
        # 1️⃣ First missed-call SMS (30s delay)
        await workflow.sleep(timedelta(seconds=30))
        await workflow.execute_activity(
            sms_send,
            args=[
                {
                    "enrollment_id": enrollment_id,
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

        # 2️⃣ Second follow-up SMS (25s later)
        await workflow.sleep(timedelta(seconds=25))
        await workflow.execute_activity(
            sms_send,
            args=[
                {
                    "enrollment_id": enrollment_id,
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

        # 3️⃣ Enroll into nurture campaign (optional, if provided)
        if nurture_campaign_id:
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
        }
