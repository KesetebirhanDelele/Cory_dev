# app/orchestrator/temporal/workflows/sms_direct_reply.py

from __future__ import annotations

from datetime import timedelta
from temporalio import workflow


@workflow.defn
class SMSDirectReplyWorkflow:
    """
    Minimal workflow that sends an immediate SMS auto-reply
    in response to an inbound SMS webhook.
    """

    @workflow.run
    async def run(self, payload: dict) -> None:
        to = payload.get("to")
        body = payload.get("body")

        if not to or not body:
            return

        await workflow.execute_activity(
            "sms_send",  # ✅ activity name, not function import
            {
                "to": to,
                "body": body,
                "skip_guards": True,
            },
            start_to_close_timeout=timedelta(seconds=30),
        )
