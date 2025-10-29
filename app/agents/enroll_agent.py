# app/agents/enroll_agent.py
from datetime import datetime, timezone, timedelta
from supabase import create_client
import uuid
from temporalio import activity

# --------------------------------------------
# 1️⃣ Enrollment logic (already in your file)
# --------------------------------------------
def enroll_contact_into_campaign(sb, org_id, contact_id, campaign_id, reason="switch"):
    """Enroll a contact into a campaign, closing any existing active ones."""
    old = (
        sb.table("campaign_enrollments")
        .select("id")
        .eq("org_id", org_id)
        .eq("contact_id", contact_id)
        .eq("status", "active")
        .limit(1)
        .execute()
        .data
    )
    if old:
        sb.table("campaign_enrollments").update(
            {
                "status": "switched",
                "ended_at": datetime.now(timezone.utc),
                "reason": reason,
            }
        ).eq("id", old[0]["id"]).execute()

    # Get first step
    step = (
        sb.table("campaign_steps")
        .select("*")
        .eq("campaign_id", campaign_id)
        .order("order_id", asc=True)
        .limit(1)
        .execute()
        .data[0]
    )

    wait_ms = step.get("wait_before_ms") or 0
    next_run_at = datetime.now(timezone.utc) + timedelta(milliseconds=wait_ms)

    new_row = {
        "org_id": org_id,
        "contact_id": contact_id,
        "campaign_id": campaign_id,
        "status": "active",
        "started_at": datetime.now(timezone.utc),
        "current_step_id": step["id"],
        "next_channel": step["channel"],
        "next_run_at": next_run_at,
    }
    new_enroll = (
        sb.table("campaign_enrollments").insert(new_row).execute().data[0]
    )

    if old:
        sb.table("campaign_enrollments").update(
            {"switched_to_enrollment": new_enroll["id"]}
        ).eq("id", old[0]["id"]).execute()

    return new_enroll["id"]


# --------------------------------------------
# 2️⃣ Simulated follow-up message generator
# --------------------------------------------
@activity.defn
async def generate_followup_message(lead: dict) -> str:
    """
    Generate a simulated follow-up message based on channel type.
    Used by SimulatedFollowupWorkflow.
    """
    name = lead.get("name", "there")
    channel = lead.get("next_channel", "sms")

    if channel == "sms":
        return f"Hi {name}, just checking if you had a chance to look at our program options!"
    elif channel == "email":
        return f"Subject: Let's stay in touch\n\nHi {name}, we’d love to help you get started with your application."
    elif channel == "voice":
        return f"This is a reminder call for {name} about program enrollment options."
    else:
        return f"Hello {name}, this is your follow-up from our admissions team."
