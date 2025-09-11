# enroll_agent.py
from datetime import datetime, timezone, timedelta
from supabase import create_client
import uuid

def enroll_contact_into_campaign(sb, org_id, contact_id, campaign_id, reason="switch"):
    # close old active
    old = sb.table("campaign_enrollments").select("id").eq("org_id", org_id).eq("contact_id", contact_id).eq("status","active").limit(1).execute().data
    if old:
        sb.table("campaign_enrollments").update({"status":"switched","ended_at":datetime.now(timezone.utc),"reason":reason}).eq("id", old[0]["id"]).execute()

    # entry step
    step = (sb.table("campaign_steps")
              .select("*")
              .eq("campaign_id", campaign_id)
              .order("order_id", asc=True)
              .limit(1).execute().data)[0]
    wait_ms = step.get("wait_before_ms") or 0
    next_run_at = datetime.now(timezone.utc) + timedelta(milliseconds=wait_ms)

    new_row = {
        "org_id": org_id, "contact_id": contact_id, "campaign_id": campaign_id,
        "status":"active","started_at":datetime.now(timezone.utc),
        "current_step_id": step["id"], "next_channel": step["channel"],
        "next_run_at": next_run_at
    }
    new_enroll = sb.table("campaign_enrollments").insert(new_row).execute().data[0]
    if old:
        sb.table("campaign_enrollments").update({"switched_to_enrollment": new_enroll["id"]}).eq("id", old[0]["id"]).execute()
    return new_enroll["id"]
