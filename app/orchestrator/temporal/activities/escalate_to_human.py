from temporalio import activity
import logging

@activity.defn
async def escalate_to_human(lead: dict) -> dict:
    logging.info(f"[ESCALATION] Escalating lead {lead['id']} ({lead['name']}) to advisor.")
    return {"status": "notified", "lead_id": lead["id"]}
