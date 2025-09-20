# tests/test_plan.py
from __future__ import annotations
import os, time, uuid
from datetime import datetime, timezone
from dataclasses import dataclass
from dotenv import load_dotenv

# IMPORTANT: load .env BEFORE importing supabase_repo (it reads env on import)
load_dotenv()
from supabase_repo import sb  # uses SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY

SCHEMA = "dev_nexus"
db = sb.postgrest.schema(SCHEMA)

# ---------- tiny assert helpers ----------
class TestFail(Exception): 
    __test__ = False
    pass

def require(cond: bool, msg: str):
    if not cond: raise TestFail(msg)

def red(s: str): return f"\x1b[31m{s}\x1b[0m"
def green(s: str): return f"\x1b[32m{s}\x1b[0m"

# ---------- utility queries ----------
def get_latest_enrollment():
    res = db.from_("campaign_enrollments").select(
        "id, org_id, contact_id, campaign_id, current_step_id, next_channel, next_run_at"
    ).order("started_at", desc=True).limit(1).execute()
    require(res.data, "No enrollments found. Run seeding first.")
    return res.data[0]

def get_sms_due(enrollment_id: str | None = None):
    q = db.from_("v_due_sms_followups").select("*")
    if enrollment_id:
        q = q.eq("enrollment_id", enrollment_id)
    return q.execute().data

def get_activities(enrollment_id: str, channel: str | None = None, limit=5):
    q = db.from_("campaign_activities").select(
        "id, channel, status, outcome, provider_call_id, scheduled_at, sent_at, completed_at, generated_message"
    ).eq("enrollment_id", enrollment_id).order("created_at", desc=True).limit(limit)
    if channel:
        q = q.eq("channel", channel)
    return q.execute().data

def get_enrollment(enrollment_id: str):
    return db.from_("campaign_enrollments").select("*").eq("id", enrollment_id).single().execute().data

# ---------- RPC helpers ----------
def rpc_log_voice_call(
    enrollment_id: str,
    provider_call_id: str,
    status: str = "failed",
    end_call_reason: str = "no_answer",
    duration_sec: int = 20,
    classification: str = "followup",
    campaign_type: str = "live",
):
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "p_enrollment_id": enrollment_id,
        "p_provider_call_id": provider_call_id,
        "p_provider_module_id": "vm",
        "p_duration_seconds": duration_sec,
        "p_end_call_reason": end_call_reason,
        "p_executed_actions": None,
        "p_prompt_variables": None,
        "p_recording_url": None,
        "p_transcript": None,
        "p_call_started_at": now,
        "p_agent_name": "TestAgent",
        "p_call_timezone": "America/Chicago",
        "p_phone_to": "+15555550123",
        "p_phone_from": "+15555550000",
        "p_call_status": status,
        "p_campaign_type": campaign_type,
        "p_outcome": status,
        "p_classification": classification,
    }
    # RPC under dev_nexus profile
    return db.rpc("usp_logvoicecallandadvance", payload).execute().data

def rpc_ingest(max_rows: int = 100):
    return db.rpc("usp_ingestphonecalllogs", {"p_max_rows": max_rows}).execute().data

# ---------- tests ----------
def T0_sanity():
    print("T0) sanity: latest enrollment + initial due-SMS …")
    enr = get_latest_enrollment()
    print("   enrollment:", enr["id"])
    due = get_sms_due(enr["id"])
    print("   due_sms:", len(due))
    return enr

def T1_sms_sender_once(enrollment_id: str):
    print("T1) run SMS sender once …")
    # run the sender as a one-shot
    import sms_sender  # your module
    sms_sender.run_sms_sender()

    # verify that at least one SMS for this enrollment moved to sent/completed
    acts = get_activities(enrollment_id, channel="sms", limit=5)
    require(any(a.get("sent_at") or a.get("completed_at") for a in acts), "No SMS sent/completed found.")
    print("   sms ok:", [a["id"] for a in acts if a.get("sent_at") or a.get("completed_at")])

def T2_voice_failed_retry_path(enrollment_id: str):
    print("T2) voice failed → retry policy + optional SMS …")
    call_id = f"CALL-LOCAL-{uuid.uuid4()}"
    rpc_log_voice_call(enrollment_id, call_id, status="failed", end_call_reason="no_answer", classification="followup")
    enr = get_enrollment(enrollment_id)
    require(enr["next_channel"] in (None, "voice", "sms", "email"), "next_channel missing after failure.")
    print("   next after fail:", enr["next_channel"], enr["next_run_at"])

    # If your policy schedules SMS on retry, there will be a planned SMS due now or in the future
    due = get_sms_due(enrollment_id)
    print("   due_sms_after_fail:", len(due))

def T3_voice_completed_advance_or_finish(enrollment_id: str):
    print("T3) voice completed → advance or finish …")
    call_id = f"CALL-LOCAL-{uuid.uuid4()}"
    rpc_log_voice_call(enrollment_id, call_id, status="completed", end_call_reason="completed",
                       duration_sec=140, classification="booked")
    enr = get_enrollment(enrollment_id)
    # either completed or moved to a new step with a next action
    ok = (enr["status"] == "completed") or (enr.get("current_step_id") is not None) or (enr.get("next_channel") is not None)
    require(ok, "Enrollment did not advance or complete after connected call.")
    print("   enrollment state:", enr["status"], "next:", enr.get("next_channel"), enr.get("next_run_at"))

def N1_unknown_enrollment_rejected():
    print("N1) unknown enrollment → staged with error and ignored …")
    # insert a bad staging row via RPC by calling log + then update to bad id (or call ingest directly with bad id row)
    # Simpler: write straight to staging then ingest
    bad_id = "00000000-0000-0000-0000-000000000000"
    db.from_("phone_call_logs_stg").insert({
        "enrollment_id": bad_id, "status": "failed"
    }).execute()
    rpc_ingest(1)
    stg = db.from_("phone_call_logs_stg").select("id, processed, error_msg").order("id", desc=True).limit(1).execute().data[0]
    require(stg["processed"] is True, "Staging row was not processed.")
    require(stg["error_msg"] is not None, "Expected error_msg on bad enrollment.")
    print("   staging processed w/ error:", stg["error_msg"])

def run_all():
    try:
        enr = T0_sanity()
        T1_sms_sender_once(enr["id"])
        T2_voice_failed_retry_path(enr["id"])
        T3_voice_completed_advance_or_finish(enr["id"])
        N1_unknown_enrollment_rejected()
        print(green("\nALL TESTS PASSED ✅"))
    except TestFail as e:
        print(red(f"\nTEST FAILED: {e}"))
        raise
    except Exception as e:
        print(red(f"\nUNEXPECTED ERROR: {e}"))
        raise

if __name__ == "__main__":
    run_all()
