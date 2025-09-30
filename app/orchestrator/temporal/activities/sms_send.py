# from temporalio import activity
# # Low-level provider client (you already have): app.channels.providers.sms
# from app.channels.providers import sms as sms_client
# from app.data import supabase_repo as repo

# @activity.defn
# async def run(enrollment_id: str, payload: dict) -> dict:
#     """payload: {'to': str, 'body': str, 'idempotency_key': str?}"""
#     ref = await sms_client.send(to=payload["to"], body=payload["body"], idempotency_key=payload.get("idempotency_key"))
#     # optional: log outbound
#     try:
#         await repo.log_outbound(enrollment_id=enrollment_id, channel="sms", provider_ref=ref)
#     except Exception:
#         pass
#     return {"provider_ref": ref}

from temporalio import activity
from typing import Dict, Any

@activity.defn(name="sms_send")
async def sms_send(enrollment_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Stub SMS activity. Returns a fake provider reference."""
    return {
        "channel": "sms",
        "enrollment_id": enrollment_id,
        "provider_ref": f"stub-sms-{enrollment_id}",
        "status": "queued",
        "request": payload,
    }
