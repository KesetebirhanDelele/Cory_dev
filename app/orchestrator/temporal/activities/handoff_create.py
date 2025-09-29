from temporalio import activity
from app.handoff import slack as slack_client  # if you have it; otherwise stub

@activity.defn
async def run(enrollment_id: str, reason: str = "manual") -> dict:
    try:
        ticket_id = await slack_client.create_ticket(enrollment_id=enrollment_id, reason=reason)
    except Exception:
        ticket_id = None
    return {"ticket_id": ticket_id}
