from temporalio import activity
from app.channels.providers import voice as voice_client
from app.data import supabase_repo as repo

@activity.defn
async def run(enrollment_id: str, payload: dict) -> dict:
    """payload: {'to': str, 'script_id': str, 'idempotency_key': str?}"""
    ref = await voice_client.start_call(to=payload["to"], script_id=payload.get("script_id"), idempotency_key=payload.get("idempotency_key"))
    try:
        await repo.log_outbound(enrollment_id=enrollment_id, channel="voice", provider_ref=ref)
    except Exception:
        pass
    return {"provider_ref": ref}
