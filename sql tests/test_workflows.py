# tests/test_workflows.py
from __future__ import annotations
import os, uuid, time
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()
# Uses SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY and SCHEMA=dev_nexus by default
from supabase_repo import sb
import sms_sender  # uses the patched async-safe version

SCHEMA = os.getenv("SUPABASE_SCHEMA", "dev_nexus")
db = sb.postgrest.schema(SCHEMA)

def _now(): return datetime.now(timezone.utc).isoformat()

def _print(title, data): print(f"\n=== {title} ===\n", data)

# -------- helpers --------
def get_or_create_contact(org_id:str, phone:str="+15555550123", first="Ada", last="Lovelace"):
    # try find
    r = db.from_("contacts").select("id").eq("org_id", org_id).eq("phone", phone).limit(1).execute().data
    if r: return r[0]["id"]
    # create
    return db.from_("contacts").insert({
        "org_id": org_id, "first_name": first, "last_name": last, "phone": phone
    }).execute().data[0]["id"]

def ensure_campaign_with_steps(org_id:str, name="WF Demo Campaign"):
    # ensure campaign
    r = db.from_("campaigns").select("id").eq("org_id", org_id).eq("name", name).limit(1).execute().data
    if r:
        camp_id = r[0]["id"]
    else:
        camp_id = db.from_("campaigns").insert({
            "org_id": org_id, "name": name, "goal_prompt": "Demo", "campaign_type": "live"
        }).execute().data[0]["id"]
    # ensure steps: voice (order 1) then sms (order 2)
    steps = db.from_("campaign_steps").select("id,order_id,channel").eq("campaign_id", camp_id).execute().data
    have1 = any(s["order_id"]==1 and s["channel"]=="voice" for s in steps)
    have2 = any(s["order_id"]==2 and s["channel"]=="sms" for s in steps)
    if not have1:
        db.from_("campaign_steps").insert({
            "campaign_id": camp_id, "order_id": 1, "channel": "voice", "wait_before_ms": 0, "label": "Initial call"
        }).execute()
    if not have2:
        db.from_("campaign_steps").insert({
            "campaign_id": camp_id, "order_id": 2, "channel": "sms", "wait_before_ms": 0, "label": "Followup SMS"
        }).execute()
    return camp_id

def rpc(name:str, payload:dict|None=None):
    return db.rpc(name, payload or {}).execute().data

def latest_enrollment():
    d = db.from_("campaign_enrollments").select("*").order("started_at", desc=True).limit(1).execute().data
    assert d, "No enrollments—run seed_minimal first."
    return d[0]

def due_sms(enrollment_id=None):
    q = db.from_("v_due_sms_followups").select("*").order("scheduled_at", desc=False)
    if enrollment_id: q = q.eq("enrollment_id", enrollment_id)
    return q.execute().data

def activities(enrollment_id:str, channel=None):
    q = db.from_("campaign_activities").select("*").eq("enrollment_id", enrollment_id).order("created_at", desc=True)
    if channel: q = q.eq("channel", channel)
    return q.execute().data

# -------- workflow simulations --------

def WF1_campaign_builder_and_enrollment():
    """1) Build campaign & steps, 2) Enroll contact (usp_EnrollContactIntoCampaign)"""
    org = db.from_("organizations").select("id,name").limit(1).execute().data[0]
    camp = ensure_campaign_with_steps(org["id"])
    contact = get_or_create_contact(org["id"])
    enr_id = rpc("usp_enrollcontactintocampaign", {
        "p_org_id": org["id"], "p_contact_id": contact, "p_campaign_id": camp, "p_reason": "test"
    })
    _print("WF1 enrolled", {"enrollment_id": enr_id})
    return enr_id

def WF2_do_actions_orchestrator_sms(enrollment_id:str):
    """3) Orchestrator: force next action to SMS now; 4b) SMS Sender picks it up."""
    # set a planned SMS activity (what your orchestrator would do) or rely on view from seed
    # simplest: insert a planned sms activity for current step now:
    enr = db.from_("campaign_enrollments").select("org_id,campaign_id,current_step_id").eq("id", enrollment_id).single().execute().data
    db.from_("campaign_activities").insert({
        "org_id": enr["org_id"], "enrollment_id": enrollment_id, "campaign_id": enr["campaign_id"],
        "step_id": enr["current_step_id"], "channel": "sms", "status": "planned",
        "scheduled_at": _now(), "generated_message": "Hello from WF2!"
    }).execute()
    # run the sender once
    sms_sender.run_sms_sender()
    sms = activities(enrollment_id, "sms")
    _print("WF2 sms activities", [(a["id"], a["status"], a.get("sent_at")) for a in sms[:3]])

def WF3_voice_failed_retry(enrollment_id:str):
    """4a) Voice placed -> 5) provider result (failed) -> 6) ingest -> 7) policy schedules retry"""
    call_id = f"WF-FAIL-{uuid.uuid4()}"
    rpc("usp_logvoicecallandadvance", {
        "p_enrollment_id": enrollment_id,
        "p_provider_call_id": call_id,
        "p_provider_module_id": "vm",
        "p_duration_seconds": 20,
        "p_end_call_reason": "no_answer",
        "p_executed_actions": None,
        "p_prompt_variables": None,
        "p_recording_url": None,
        "p_transcript": None,
        "p_call_started_at": _now(),
        "p_agent_name": "Bot",
        "p_call_timezone": "America/Chicago",
        "p_phone_to": "+15555550123",
        "p_phone_from": "+15555550000",
        "p_call_status": "failed",
        "p_campaign_type": "live",
        "p_outcome": "failed",
        "p_classification": "followup"
    })
    enr = db.from_("campaign_enrollments").select("next_channel,next_run_at,status").eq("id", enrollment_id).single().execute().data
    _print("WF3 enrollment next", enr)

def WF4_voice_completed_advance_or_complete(enrollment_id:str):
    """4a) Voice placed -> completed -> advance to next step or complete enrollment"""
    call_id = f"WF-DONE-{uuid.uuid4()}"
    rpc("usp_logvoicecallandadvance", {
        "p_enrollment_id": enrollment_id,
        "p_provider_call_id": call_id,
        "p_provider_module_id": "vm",
        "p_duration_seconds": 140,
        "p_end_call_reason": "completed",
        "p_executed_actions": None,
        "p_prompt_variables": None,
        "p_recording_url": "https://example/rec.mp3",
        "p_transcript": "Great call.",
        "p_call_started_at": _now(),
        "p_agent_name": "Bot",
        "p_call_timezone": "America/Chicago",
        "p_phone_to": "+15555550123",
        "p_phone_from": "+15555550000",
        "p_call_status": "completed",
        "p_campaign_type": "live",
        "p_outcome": "booked",
        "p_classification": "booked"
    })
    enr = db.from_("campaign_enrollments").select("status,current_step_id,next_channel,next_run_at,ended_at").eq("id", enrollment_id).single().execute().data
    _print("WF4 enrollment state", enr)

def WF5_idempotency_same_call_twice(enrollment_id:str):
    """Call the same provider_call_id twice to prove duplicates are blocked by unique index."""
    call_id = f"WF-DEDUP-{uuid.uuid4()}"
    for i in range(2):
        try:
            rpc("usp_logvoicecallandadvance", {
                "p_enrollment_id": enrollment_id,
                "p_provider_call_id": call_id,
                "p_provider_module_id": "vm",
                "p_duration_seconds": 60,
                "p_end_call_reason": "completed",
                "p_executed_actions": None,
                "p_prompt_variables": None,
                "p_recording_url": None,
                "p_transcript": None,
                "p_call_started_at": _now(),
                "p_agent_name": "Bot",
                "p_call_timezone": "America/Chicago",
                "p_phone_to": "+15555550123",
                "p_phone_from": "+15555550000",
                "p_call_status": "completed",
                "p_campaign_type": "live",
                "p_outcome": "completed",
                "p_classification": "booked"
            })
        except Exception as e:
            _print("WF5 second insert blocked (expected)", str(e))
    # Count activities with that provider_call_id
    cnt = db.from_("campaign_activities").select("id", count="exact").eq("provider_call_id", call_id).execute()
    _print("WF5 count by provider_call_id", {"provider_call_id": call_id, "count": cnt.count})

def WF6_policy_override_retry_sms(enrollment_id:str):
    """Demonstrate per-campaign override that schedules SMS on retry."""
    enr = db.from_("campaign_enrollments").select("campaign_id").eq("id", enrollment_id).single().execute().data
    camp = enr["campaign_id"]
    # Upsert override: schedule SMS and short retry on failures
    db.from_("campaign_call_policies").upsert({
        "campaign_id": camp,
        "status": "failed",
        "end_call_reason": "no_answer",
        "is_connected": False,
        "should_retry": True,
        "retry_sms": True,           # <—
        "first_retry_mins": 1,
        "next_retry_mins": 1,
        "max_retry_days": 1,
        "align_same_time": False
    }).execute()
    # Trigger a failed call again
    WF3_voice_failed_retry(enrollment_id)
    # Give the policy a moment then check due sms view
    time.sleep(1)
    _print("WF6 due_sms_after_override", due_sms(enrollment_id))

def WF7_unknown_enrollment_guard():
    """Insert a bogus staging row; ingest should mark error and not mutate state."""
    db.from_("phone_call_logs_stg").insert({"enrollment_id": "00000000-0000-0000-0000-000000000000", "status":"failed"}).execute()
    rpc("usp_ingestphonecalllogs", {"p_max_rows": 1})
    stg = db.from_("phone_call_logs_stg").select("id,processed,error_msg").order("id", desc=True).limit(1).execute().data[0]
    _print("WF7 staging result", stg)

def run_all():
    # Build + enroll
    enr = WF1_campaign_builder_and_enrollment()
    # Orchestrator/SMS path
    WF2_do_actions_orchestrator_sms(enr)
    # Voice fail path -> retry
    WF3_voice_failed_retry(enr)
    # Optional: show policy override that schedules SMS on retry
    WF6_policy_override_retry_sms(enr)
    # Voice complete -> advance or finish
    WF4_voice_completed_advance_or_complete(enr)
    # Duplicate protection
    WF5_idempotency_same_call_twice(enr)
    # Unknown enrollment safety
    WF7_unknown_enrollment_guard()
    print("\n✅ Workflow simulations completed.")

if __name__ == "__main__":
    run_all()
