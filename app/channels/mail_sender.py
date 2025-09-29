# mail_sender.py
import os
import asyncio
import inspect
import logging
from datetime import datetime, timezone

from app.data.supabase_repo import sb  # uses SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY
try:
    # Implement this later with your real provider (e.g., Mandrill/SendGrid)
    # Signature expected: send_email(to_email: str, subject: str, body: str) -> provider_ref (str)
    from providers.email import send_email
except Exception:  # simple mock fallback
    async def send_email(to_email: str, subject: str, body: str) -> str:
        return f"mock-email:{to_email}"

SCHEMA = os.getenv("SUPABASE_SCHEMA", "dev_nexus")
EMAIL_RATE_LIMIT_MS = int(os.getenv("EMAIL_RATE_LIMIT_MS", "0"))
DEFAULT_SUBJECT = os.getenv("EMAIL_SUBJECT_TEMPLATE", "Follow-up from our call")

def _db():
    return sb.postgrest.schema(SCHEMA)

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def fetch_due_emails(limit: int = 100):
    return (
        _db().from_("v_due_email_followups")
        .select("*")
        .order("scheduled_at", desc=False)
        .limit(limit)
        .execute()
        .data
    )

def update_activity(activity_id: str, patch: dict):
    _db().from_("campaign_activities").update(patch).eq("id", activity_id).execute()

async def _call_send_email(to_email: str, subject: str, body: str):
    """Support both async and sync provider implementations."""
    if inspect.iscoroutinefunction(send_email):
        return await send_email(to_email, subject, body)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, send_email, to_email, subject, body)

async def _send_one(row: dict):
    activity_id = row["activity_id"]
    to_email    = row.get("contact_email")
    fname       = (row.get("first_name") or "").strip()
    lname       = (row.get("last_name") or "").strip()
    greeting    = f"{fname} {lname}".strip() or "there"
    body        = row.get("generated_message") or f"Hi {greeting}, following up as discussed."
    subject     = DEFAULT_SUBJECT

    try:
        provider_ref = await _call_send_email(to_email, subject, body)
        update_activity(activity_id, {
            "status": "completed",
            "sent_at": _now_iso(),
            "completed_at": _now_iso(),
            "provider_ref": provider_ref,
            "generated_message": body,
            "prompt_used": subject
        })
    except Exception as ex:
        logging.exception("Email send failed for activity %s: %s", activity_id, ex)
        update_activity(activity_id, {
            "status": "failed",
            "completed_at": _now_iso(),
            "ai_analysis": f"Email send failed: {ex}"
        })

    if EMAIL_RATE_LIMIT_MS > 0:
        await asyncio.sleep(EMAIL_RATE_LIMIT_MS / 1000.0)

async def _run_async() -> int:
    rows = fetch_due_emails()
    if not rows:
        return 0
    for r in rows:
        await _send_one(r)
    return len(rows)

def run_mail_sender() -> int:
    """Sync entry point for CLI/workers/tests."""
    return asyncio.run(_run_async())

if __name__ == "__main__":
    processed = run_mail_sender()
    print(f"Processed {processed} email(s)")
