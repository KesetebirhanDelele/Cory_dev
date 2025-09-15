# call_processing_agent.py
# from db import sb
from supabase_repo import sb
from datetime import datetime, timezone, timedelta

ANY = "ANY"

def policy_for(campaign_id, status, reason):
    # campaign-level first
    pol = (sb.table("campaign_call_policies")
             .select("*")
             .eq("campaign_id", campaign_id)
             .in_("status", [status or ANY, ANY])
             .in_("end_call_reason", [reason or ANY, ANY])
             .execute().data)
    if pol:
        pol.sort(key=lambda p: (0 if p["status"]==(status or ANY) else 1,
                                0 if p["end_call_reason"]==(reason or ANY) else 1))
        return pol[0]
    # fallback globals
    glob = (sb.table("phone_log_decisions")
              .select("*")
              .in_("status", [status or ANY, ANY])
              .in_("end_call_reason", [reason or ANY, ANY])
              .execute().data)
    if glob:
        glob.sort(key=lambda d: (0 if d["status"]==(status or ANY) else 1,
                                 0 if d["end_call_reason"]==(reason or ANY) else 1))
        # fill defaults
        g = glob[0]
        g["first_retry_mins"] = g.get("first_retry_mins") or 1440
        g["next_retry_mins"]  = g.get("next_retry_mins")  or 1440
        g["max_retry_days"]   = g.get("max_retry_days")   or 4
        g["align_same_time"]  = g.get("align_same_time")  if g.get("align_same_time") is not None else True
        return g
    # safe default
    return {"is_connected": False,"should_retry": False,"retry_sms": False,
            "first_retry_mins": 1440,"next_retry_mins": 1440,"max_retry_days": 4,"align_same_time": True}

def count_attempts(enrollment_id, step_id):
    return (sb.table("campaign_activities").select("id", count="exact")
              .eq("enrollment_id", enrollment_id).eq("step_id", step_id).eq("channel","voice")
              .execute().count)

def schedule_sms(enrollment_id, send_at=None, message=None):
    row = {
      "enrollment_id": enrollment_id,
      "channel":"sms","status":"planned",
      "scheduled_at": send_at or datetime.now(timezone.utc)
    }
    # Need org_id/campaign_id/step_id for activity row:
    e = sb.table("campaign_enrollments").select("*").eq("id", enrollment_id).single().execute().data
    row.update({"org_id": e["org_id"], "campaign_id": e["campaign_id"], "step_id": e["current_step_id"]})
    sb.table("campaign_activities").insert(row).execute()

def process_one(stg):
    enrollment_id = stg.get("enrollment_id")
    if not enrollment_id:
        # Try resolve by contact_id
        if stg.get("contact_id"):
            active = (sb.table("campaign_enrollments").select("*")
                        .eq("contact_id", stg["contact_id"]).eq("status","active")
                        .order("started_at", desc=True).limit(1).execute().data)
            if not active: 
                sb.table("phone_call_logs_stg").update({"processed":True,"processed_at":datetime.now(timezone.utc),"error_msg":"no active enrollment"}).eq("id", stg["id"]).execute()
                return
            enrollment_id = active[0]["id"]

    e = sb.table("campaign_enrollments").select("*").eq("id", enrollment_id).single().execute().data
    if not e or e["status"] != "active":
        sb.table("phone_call_logs_stg").update({"processed":True,"processed_at":datetime.now(timezone.utc),"error_msg":"not active"}).eq("id", stg["id"]).execute()
        return

    # Log voice activity
    act = {
      "org_id": e["org_id"], "enrollment_id": e["id"], "campaign_id": e["campaign_id"], "step_id": e["current_step_id"],
      "attempt_no": 1, "channel":"voice","status":"completed",
      "scheduled_at": stg.get("start_time") or datetime.now(timezone.utc),
      "sent_at": stg.get("start_time") or datetime.now(timezone.utc),
      "completed_at": datetime.now(timezone.utc),
      "outcome": stg.get("status"),
      "provider_ref": stg.get("call_id"),
      "provider_call_id": stg.get("call_id"),
      "provider_module_id": stg.get("module_id"),
      "call_duration_sec": stg.get("duration_seconds"),
      "end_call_reason": stg.get("end_call_reason"),
      "executed_actions_json": stg.get("executed_actions"),
      "prompt_variables_json": stg.get("prompt_variables"),
      "recording_url": stg.get("recording_url"),
      "transcript": stg.get("transcript"),
      "call_started_at": stg.get("start_time") or datetime.now(timezone.utc),
      "agent_name": stg.get("agent"),
      "call_timezone": stg.get("timezone"),
      "phone_number_to": stg.get("phone_number_to"),
      "phone_number_from": stg.get("phone_number_from"),
      "call_status": stg.get("status"),
      "campaign_type": stg.get("campaign_type")
    }
    sb.table("campaign_activities").insert(act).execute()

    # Decision
    pol = policy_for(e["campaign_id"], stg.get("status"), stg.get("end_call_reason"))

    # Retry branch
    if not pol["is_connected"] and pol["should_retry"]:
        # window
        enroll_started = e["started_at"]
        if datetime.now(timezone.utc) < (datetime.fromisoformat(enroll_started.replace("Z","+00:00")) + timedelta(days=pol["max_retry_days"])):
            attempts = count_attempts(e["id"], e["current_step_id"]) or 0
            mins = pol["first_retry_mins"] if attempts <= 1 else pol["next_retry_mins"]
            next_run = datetime.now(timezone.utc) + timedelta(minutes=mins)

            if pol["align_same_time"]:
                # align to first voice call time-of-day in this step
                first = (sb.table("campaign_activities").select("call_started_at")
                           .eq("enrollment_id", e["id"]).eq("step_id", e["current_step_id"]).eq("channel","voice")
                           .order("call_started_at", asc=True).limit(1).execute().data)
                if first and first[0]["call_started_at"]:
                    t = datetime.fromisoformat(first[0]["call_started_at"].replace("Z","+00:00"))
                    next_run = next_run.replace(hour=t.hour, minute=t.minute, second=t.second, microsecond=0)

            sb.table("campaign_enrollments").update({"next_channel":"voice","next_run_at": next_run, "updated_at": datetime.now(timezone.utc)}).eq("id", e["id"]).execute()

            if pol["retry_sms"]:
                schedule_sms(e["id"], send_at=datetime.now(timezone.utc))

            sb.table("phone_call_logs_stg").update({"processed":True,"processed_at":datetime.now(timezone.utc),"error_msg":None}).eq("id", stg["id"]).execute()
            return
        # else fallthrough to classification

    # Connected or window expired → classification path
    cl = stg.get("classification") or "followup"
    if cl in ("booked","appointment_booked","cold","not_interested","dnc"):
        sb.table("campaign_enrollments").update({
          "status":"completed","ended_at":datetime.now(timezone.utc),
          "current_step_id": None, "next_channel": None, "next_run_at": None, "updated_at": datetime.now(timezone.utc)
        }).eq("id", e["id"]).execute()
    else:
        # advance to next step
        next_step = (sb.table("campaign_steps").select("*")
                       .eq("campaign_id", e["campaign_id"])
                       .gt("order_id", sb.table("campaign_steps").select("order_id").eq("id", e["current_step_id"]).single().execute().data["order_id"])
                       .order("order_id", asc=True).limit(1).execute().data)
        if not next_step:
            sb.table("campaign_enrollments").update({
              "status":"completed","ended_at":datetime.now(timezone.utc),
              "current_step_id": None, "next_channel": None, "next_run_at": None, "updated_at": datetime.now(timezone.utc)
            }).eq("id", e["id"]).execute()
        else:
            ns = next_step[0]
            wait_ms = ns.get("wait_before_ms") or 0
            delta = timedelta(milliseconds=wait_ms)
            sb.table("campaign_enrollments").update({
              "current_step_id": ns["id"], "next_channel": ns["channel"],
              "next_run_at": datetime.now(timezone.utc) + delta, "updated_at": datetime.now(timezone.utc)
            }).eq("id", e["id"]).execute()

    sb.table("phone_call_logs_stg").update({"processed":True,"processed_at":datetime.now(timezone.utc),"error_msg":None}).eq("id", stg["id"]).execute()

async def run_call_processing_once():
    rows = sb.table("phone_call_logs_stg").select("*").eq("processed", False).order("id", asc=True).limit(100).execute().data
    for r in rows:
        try:
            process_one(r)
        except Exception as ex:
            sb.table("phone_call_logs_stg").update({"error_msg": str(ex)}).eq("id", r["id"]).execute()
