# voice_dialer.py
from datetime import datetime, timezone
from db import init_db_pool, fetch_due_actions, update_activity, insert_activity
from providers.voice import place_call

# fetch_due_actions should surface enrollments with next_channel='voice' and next_run_at <= now

async def run_voice_dialer():
    await init_db_pool()
    due = await fetch_due_actions()
    for r in due:
        if r.get("next_channel") != "voice":
            continue

        # create an activity row in 'initiated' state
        act = {
            "org_id": r["org_id"],
            "enrollment_id": r["enrollment_id"],
            "campaign_id": r["campaign_id"],
            "step_id": r["current_step_id"],
            "attempt_no": 1,
            "channel": "voice",
            "status": "initiated",
            "scheduled_at": r.get("next_run_at"),
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }
        new_act = await insert_activity(act)
        activity_id = new_act["id"]

        # you’ll usually look up numbers from contact or org settings
        to_number   = r["contact_phone"]
        from_number = r["org_from_number"]
        provider_ref = await place_call(to_number, from_number, {
            "org_id": r["org_id"],
            "enrollment_id": r["enrollment_id"],
            "activity_id": activity_id
        })

        await update_activity(activity_id, {
            "status": "sent",
            "provider_ref": provider_ref
        })
