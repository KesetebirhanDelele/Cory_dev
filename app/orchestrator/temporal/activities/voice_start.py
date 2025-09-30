# from temporalio import activity
# from app.channels.providers import voice as voice_client
# from app.data import supabase_repo as repo

# @activity.defn
# async def run(enrollment_id: str, payload: dict) -> dict:
#     """payload: {'to': str, 'script_id': str, 'idempotency_key': str?}"""
#     ref = await voice_client.start_call(to=payload["to"], script_id=payload.get("script_id"), idempotency_key=payload.get("idempotency_key"))
#     try:
#         await repo.log_outbound(enrollment_id=enrollment_id, channel="voice", provider_ref=ref)
#     except Exception:
#         pass
#     return {"provider_ref": ref}

from temporalio import activity
from typing import Dict, Any

@activity.defn(name="voice_start")
async def voice_start(enrollment_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "channel": "voice",
        "enrollment_id": enrollment_id,
        "provider_ref": f"stub-voice-{enrollment_id}",
        "status": "queued",
        "request": payload,
    }
