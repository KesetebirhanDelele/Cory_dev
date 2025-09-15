# sms_sender.py  (patched)
import os
import asyncio
import inspect
import logging
from datetime import datetime, timezone

from providers.sms import send_sms
from supabase_repo import fetch_due_sms_via_supabase, update_activity_via_supabase
# fetch/update helpers already exist and target the view/table we need. :contentReference[oaicite:1]{index=1} :contentReference[oaicite:2]{index=2}

# Optional throttle between messages (ms). Set SMS_RATE_LIMIT_MS=250 etc in .env if desired.
RATE_LIMIT_MS = int(os.getenv("SMS_RATE_LIMIT_MS", "0"))

async def _call_send_sms(org_id: str, enrollment_id: str, body: str):
    """
    Call providers.sms.send_sms safely.
    - If it's async: await it.
    - If it's sync: run it in a thread so we don't block the event loop.
    """
    if inspect.iscoroutinefunction(send_sms):
        return await send_sms(org_id, enrollment_id, body)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, send_sms, org_id, enrollment_id, body)

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

async def _send_one(row: dict) -> None:
    activity_id = row["activity_id"]
    body = row.get("generated_message") or (
        "Hi! Just tried calling—I'll try again shortly. Reply if you'd prefer a different time."
    )

    try:
        provider_ref = await _call_send_sms(row["org_id"], row["enrollment_id"], body)
        update_activity_via_supabase(
            activity_id,
            {
                "status": "completed",
                "sent_at": _now_iso(),
                "completed_at": _now_iso(),
                "provider_ref": provider_ref,
                "generated_message": body,
            },
        )
    except Exception as ex:
        logging.exception("SMS send failed for activity %s: %s", activity_id, ex)
        update_activity_via_supabase(
            activity_id,
            {
                "status": "failed",
                "completed_at": _now_iso(),
                "ai_analysis": f"SMS send failed: {ex}",
            },
        )

    if RATE_LIMIT_MS > 0:
        await asyncio.sleep(RATE_LIMIT_MS / 1000.0)

async def _run_async() -> int:
    rows = fetch_due_sms_via_supabase()
    if not rows:
        return 0
    for r in rows:
        await _send_one(r)
    return len(rows)

def run_sms_sender() -> int:
    """
    Synchronous entry point used by tests and workers.
    Wraps the async flow and returns the count of processed messages.
    """
    return asyncio.run(_run_async())
