"""
AdmissionsOutreachWorkflow
Simulates the timed outreach sequence:
(call → SMS → call → email → escalation)
Each call lasts up to 10 seconds unless interrupted by a signal.
"""

from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

# Safe imports (Temporal requirement)
with workflow.unsafe.imports_passed_through():
    from app.orchestrator.temporal.activities.voice_start_dev import voice_start, ACTIVE_CALLS
    from app.orchestrator.temporal.activities.sms_send import sms_send
    from app.orchestrator.temporal.activities.email_send import email_send
    from app.orchestrator.temporal.activities.escalate_to_human import escalate_to_human


@workflow.defn
class AdmissionsOutreachWorkflow:
    """Deterministic outreach workflow for Cory Admissions."""

    @workflow.run
    async def run(self, lead: dict) -> str:
        logger = workflow.logger
        self._stop_due_to_reply = False  # initialize flag

        logger.info(f"🎓 Starting Admissions Outreach Workflow for {lead['name']}")

        # 1️⃣ First phone call
        call_result_1 = await workflow.execute_activity(
            voice_start,
            args=[{"to": lead["phone"], "attempt": 1, "campaign_id": "mock"}],
            schedule_to_close_timeout=timedelta(seconds=15),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        logger.info(f"📞 First call result: {call_result_1}")

        # Stop early if replied during call
        if self._stop_due_to_reply:
            logger.info("🛑 Workflow stopped due to student reply during first call.")
            return "stopped_due_to_reply"

        # 2️⃣ Wait 20 seconds → send SMS
        await workflow.sleep(20)
        if self._stop_due_to_reply:
            logger.info("🛑 Workflow stopped before SMS due to student reply.")
            return "stopped_due_to_reply"

        sms_result = await workflow.execute_activity(
            sms_send,
            args=[lead["phone"], "Hi! This is Cory Admissions. We’d love to chat when you’re free."],
            schedule_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        logger.info(f"💬 SMS result: {sms_result}")

        # 3️⃣ Wait 30 seconds → second call
        await workflow.sleep(30)
        if self._stop_due_to_reply:
            logger.info("🛑 Workflow stopped before second call due to student reply.")
            return "stopped_due_to_reply"

        call_result_2 = await workflow.execute_activity(
            voice_start,
            args=[{"to": lead["phone"], "attempt": 2, "campaign_id": "mock"}],
            schedule_to_close_timeout=timedelta(seconds=15),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        logger.info(f"📞 Second call result: {call_result_2}")

        if call_result_2["status"] == "answered" or self._stop_due_to_reply:
            logger.info("✅ Lead answered or replied — ending sequence.")
            return "completed"

        # 4️⃣ Wait 40 seconds → email fallback
        await workflow.sleep(40)
        if self._stop_due_to_reply:
            logger.info("🛑 Workflow stopped before email due to student reply.")
            return "stopped_due_to_reply"

        email_result = await workflow.execute_activity(
            email_send,
            args=[
                lead["email"],
                "We’d love to help you explore your program options",
                "Hi! This is Cory Admissions — just following up to see if you’re still interested in applying.",
            ],
            schedule_to_close_timeout=timedelta(seconds=15),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        logger.info(f"📧 Email result: {email_result}")

        # 5️⃣ Wait 10 seconds → escalate to human advisor
        await workflow.sleep(10)
        if self._stop_due_to_reply:
            logger.info("🛑 Workflow stopped before escalation due to student reply.")
            return "stopped_due_to_reply"

        escalation_result = await workflow.execute_activity(
            escalate_to_human,
            args=[lead],
            schedule_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        logger.info(f"🧍 Escalation result: {escalation_result}")

        logger.info("🚀 Outreach sequence completed with escalation.")
        return "escalated"

    # 🧠 Signal handler for live responses
    @workflow.signal
    async def inbound_reply(self, channel: str, message: str):
        """Handle inbound student replies."""
        workflow.logger.info(f"⚠️ Inbound reply via {channel}: {message}")

        if channel == "voice":
            try:
                # Mark all active calls as answered
                for num in list(ACTIVE_CALLS.keys()):
                    ACTIVE_CALLS[num] = "answered"
                workflow.logger.info("☎️ Active call marked as answered via signal.")
            except Exception as e:
                workflow.logger.warning(f"⚠️ Could not update ACTIVE_CALLS: {e}")

        # Mark the workflow for graceful stop
        self._stop_due_to_reply = True
        workflow.logger.info("✅ Student reply received — workflow will stop soon.")
