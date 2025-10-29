# app/orchestrator/temporal/workflows/simulated_followup.py
"""
SimulatedFollowupWorkflow
-------------------------
Runs a simulated outreach cycle fully within Temporal.

- Fetch due enrollments (mocked or via Supabase)
- Agent generates next outbound message (no external API)
- Each communication is logged to Supabase (interactions table)
- Optional simulated inbound replies
- Workflow progress is visible in Temporal UI
"""

from datetime import timedelta, datetime, timezone
from temporalio import workflow
from temporalio.common import RetryPolicy

# Temporal-safe imports
with workflow.unsafe.imports_passed_through():
    from app.data import supabase_repo as repo
    from app.agents.enroll_agent import generate_followup_message


@workflow.defn
class SimulatedFollowupWorkflow:
    """Autonomous simulated agent follow-up sequence."""

    @workflow.run
    async def run(self, lead: dict) -> str:
        """
        Args:
            lead (dict): Supabase enrollment or lead record, e.g.
                {
                    "id": str,
                    "name": str,
                    "email": str,
                    "phone": str,
                    "next_channel": "sms" | "email" | "voice"
                }
        """
        logger = workflow.logger
        logger.info(f"🤖 Starting Simulated Follow-up Workflow for {lead.get('name')}")

        enrollment_id = lead["id"]
        channel = lead.get("next_channel", "sms")
        lead_name = lead.get("name", "Unknown")

        # 1️⃣ Agent generates an outbound message
        message = await workflow.execute_activity(
            generate_followup_message,
            args=[lead],
            schedule_to_close_timeout=timedelta(seconds=20),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        # 2️⃣ Log outbound message
        await workflow.execute_activity(
            repo.insert_interaction,
            args=[enrollment_id, channel, "outbound", "completed", message, "ai_generated"],
            schedule_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        logger.info(f"💬 Outbound message logged for {lead_name}")

        # 3️⃣ Wait a simulated delay (represents waiting for student)
        await workflow.sleep(5)

        # 4️⃣ Simulated inbound reply (for testing)
        import random
        if workflow.random().random() < 0.6:
            simulated_reply = workflow.random().choice([
                "Thanks, I’ll review it soon.",
                "Can you send more info about the program?",
                "Not right now, maybe next month.",
                "Yes, I’m interested — when is the deadline?",
            ])
            await workflow.execute_activity(
                repo.insert_interaction,
                args=[enrollment_id, channel, "inbound", "completed", simulated_reply, "user_reply"],
                schedule_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            logger.info(f"📩 Simulated inbound reply logged for {lead_name}")
        else:
            logger.info(f"🕓 No simulated reply for {lead_name}")

        # 5️⃣ Mark next follow-up timing in Supabase
        next_time = workflow.now().isoformat()
        await workflow.execute_activity(
        repo.patch_activity,
        args=[
            "campaign_enrollments",
            f"id=eq.{enrollment_id}",
            {
                "last_contacted_at": next_time,
                "updated_at": next_time,
                "status": "active",
            },
            ],
            schedule_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        logger.info(f"✅ Workflow completed for {lead_name}")
        return "completed"

    # 🧠 Optional: signal handler for external replies
    @workflow.signal
    async def inbound_reply(self, channel: str, message: str):
        """Handle a live inbound message signal from student."""
        workflow.logger.info(f"⚡ Inbound signal on {channel}: {message}")
        self._last_inbound = {"channel": channel, "message": message}
