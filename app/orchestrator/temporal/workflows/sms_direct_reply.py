# app/orchestrator/temporal/workflows/sms_direct_reply.py

from __future__ import annotations

from datetime import timedelta
from temporalio import workflow

from app.orchestrator.temporal.activities.sms_send import sms_send


@workflow.defn
class SMSDirectReplyWorkflow:
    """
    Minimal workflow that sends an immediate SMS auto-reply in response
    to an inbound message (e.g., from the SMS webhook).

    This workflow should be registered ONLY in the campaign worker group
    (see worker.py), not in the global workflow registry.
    """

    @workflow.run
    async def run(self, to: str, body: str) -> None:
        """
        Execute a single outbound SMS via the `sms_send` activity.

        Args:
            to (str): The destination phone number (E.164 format).
            body (str): Outbound message text for the auto-reply.
        """

        if not to or not body:
            # Defensive validation (Temporal workflows must never crash)
            workflow.logger.warn(
                f"SMSDirectReplyWorkflow received invalid args: to={to}, body length={len(body or '')}"
            )
            return

        await workflow.execute_activity(
            sms_send,
            {
                "to": to,
                "body": body,
                "project_id": None,  # auto-replies are not tied to a project
                "send_reason": "inbound-auto-reply",
            },
            schedule_to_close_timeout=timedelta(seconds=30),
        )
