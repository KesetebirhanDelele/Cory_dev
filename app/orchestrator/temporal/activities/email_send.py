from temporalio import activity
from app.channels.providers import email as email_client
from app.data import supabase_repo as repo

@activity.defn
async def run(enrollment_id: str, payload: dict) -> dict:
    """payload: {'to': str, 'subject': str, 'html': str, 'idempotency_key': str?}"""
    ref = await email_client.send(to=payload["to"], subject=payload.get("subject",""), html=payload.get("html",""), idempotency_key=payload.get("idempotency_key"))
    try:
        await repo.log_outbound(enrollment_id=enrollment_id, channel="email", provider_ref=ref)
    except Exception:
        pass
    return {"provider_ref": ref}
