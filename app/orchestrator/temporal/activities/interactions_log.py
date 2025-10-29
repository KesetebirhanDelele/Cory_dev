# app/orchestrator/temporal/activities/interactions_log.py
from temporalio import activity
from app.data import supabase_repo as repo
import logging

log = logging.getLogger("interactions_log")

@activity.defn(name="log_interaction")
async def log_interaction(
    enrollment_id: str,
    channel: str,
    direction: str = "outbound",
    content: str | None = None,
    status: str = "completed",
    message_type: str = "system_message",
    classification: dict | None = None,
) -> None:
    """
    Record an interaction in Supabase.

    - If direction == "outbound": message comes from Cory (agent-generated).
    - If direction == "inbound": message comes from the student (user input or webhook).
    - Content must be passed by caller (agent or simulation).
    """

    try:
        if not content:
            log.warning(f"⚠️ No content provided for {direction} {channel} message on enrollment {enrollment_id}")

        await repo.insert_interaction(
            enrollment_id=enrollment_id,
            channel=channel.lower(),
            direction=direction.lower(),
            status=status,
            content=content or "",
            message_type=message_type,
            classification=classification or {},
        )

        log.info(f"✅ Logged {direction} {channel.upper()} interaction for enrollment {enrollment_id}")

    except Exception as e:
        # Keep workflow resilient even if logging fails
        log.warning(f"⚠️ Failed to log interaction for {enrollment_id}: {e}")
        pass
