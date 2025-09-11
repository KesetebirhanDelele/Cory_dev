# sms_sender.py
from datetime import datetime, timezone
from providers.sms import send_sms
from supabase_repo import fetch_due_sms_via_supabase, update_activity_via_supabase

def run_sms_sender():
    rows = fetch_due_sms_via_supabase()
    for r in rows:
        activity_id = r["activity_id"]
        body = r.get("generated_message") or (
            "Hi! Just tried calling—I'll try again shortly. "
            "Reply if you'd prefer a different time."
        )
        try:
            provider_ref = send_sms(r["org_id"], r["enrollment_id"], body)  # your wrapper
            update_activity_via_supabase(activity_id, {
                "status": "completed",
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "provider_ref": provider_ref,
                "generated_message": body,
            })
        except Exception as ex:
            update_activity_via_supabase(activity_id, {
                "status": "failed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "ai_analysis": f"SMS send failed: {ex}",
            })


