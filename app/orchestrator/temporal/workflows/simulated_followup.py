# app/orchestrator/temporal/workflows/simulated_followup.py
"""
SimulatedFollowupWorkflow
-------------------------
Runs a simulated outreach cycle fully within Temporal.

- Fetch due enrollments (mocked or via Supabase)
- Agent generates next outbound message (no external API)
- Each communication is logged to Supabase (interactions table)
- Optional simulated inbound replies
- Updates campaign_enrollments timing
- (Ticket 9) If intent/next_action are present on the lead, they are
  persisted into lead_campaign_steps for downstream branching.
"""

from datetime import timedelta
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
                    "next_channel": "sms" | "email" | "voice",
                    # (optional, Ticket 9)
                    "intent": str,
                    "next_action": str,
                }
        """
        logger = workflow.logger
        logger.info(
            "🤖 Starting Simulated Follow-up Workflow for %s",
            lead.get("name"),
        )

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
            args=[
                enrollment_id,
                channel,
                "outbound",
                "completed",
                message,
                "ai_generated",
            ],
            schedule_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        logger.info("💬 Outbound message logged for %s", lead_name)

        # 3️⃣ Wait a simulated delay (represents waiting for student)
        await workflow.sleep(5)

        # 4️⃣ Simulated inbound reply (for testing)
        if workflow.random().random() < 0.6:
            simulated_reply = workflow.random().choice(
                [
                    "Thanks, I’ll review it soon.",
                    "Can you send more info about the program?",
                    "Not right now, maybe next month.",
                    "Yes, I’m interested — when is the deadline?",
                ]
            )
            await workflow.execute_activity(
                repo.insert_interaction,
                args=[
                    enrollment_id,
                    channel,
                    "inbound",
                    "completed",
                    simulated_reply,
                    "user_reply",
                ],
                schedule_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            logger.info("📩 Simulated inbound reply logged for %s", lead_name)
        else:
            logger.info("🕓 No simulated reply for %s", lead_name)

        # 4.5️⃣ (Ticket 9) Persist intent / next_action if present on lead
        intent = lead.get("intent")
        next_action = lead.get("next_action")
        if intent or next_action:
            now_iso = workflow.now().isoformat()
            await workflow.execute_activity(
                repo.patch_activity,
                args=[
                    "lead_campaign_steps",
                    f"enrollment_id=eq.{enrollment_id}",
                    {
                        "intent": intent,
                        "next_action": next_action,
                        "updated_at": now_iso,
                    },
                ],
                schedule_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            logger.info(
                "🧭 Updated lead_campaign_steps for %s with intent=%s next_action=%s",
                lead_name,
                intent,
                next_action,
            )

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

        logger.info("✅ Workflow completed for %s", lead_name)
        return "completed"

    # 🧠 Optional: signal handler for external replies
    @workflow.signal
    async def inbound_reply(self, channel: str, message: str):
        """Handle a live inbound message signal from student."""
        workflow.logger.info("⚡ Inbound signal on %s: %s", channel, message)
        self._last_inbound = {"channel": channel, "message": message}
