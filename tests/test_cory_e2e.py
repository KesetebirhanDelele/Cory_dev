# tests/test_cory_e2e.py
import os
import time
import uuid
from datetime import datetime, timezone
import pytest
import inspect
import asyncio

from tests.conftest import rest_single_by_id, sb_table, rest_insert, rest_upsert, rest_update_eq
from tests.fake_providers import sms_send, email_send, voice_place_call

def ensure_org(supabase) -> str:
    env_org = os.getenv("ORG_ID")
    if env_org:
        return env_org

    # Use existing org if present
    res = sb_table(supabase, "organizations").select("id").limit(1).execute().data
    if isinstance(res, list) and res:
        return res[0]["id"]

    # Insert a minimal valid org for your schema (includes slug)
    new = {
        "name": "Pytest Org",
        "slug": f"pytest-org-{uuid.uuid4().hex[:8]}",  # satisfy NOT NULL / unique
    }
    created = rest_insert("organizations", new)
    return created[0]["id"]


def ensure_contact(supabase, org_id: str, fake_contact: dict) -> str:
    row = {
        "org_id": org_id,
        "first_name": fake_contact["first_name"],
        "last_name": fake_contact["last_name"],
        "full_name": f'{fake_contact["first_name"]} {fake_contact["last_name"]}',
        "email": fake_contact["email"],
        "phone": fake_contact["phone"],
    }
    inserted = rest_insert("contacts", row)
    return inserted[0]["id"]


def ensure_campaign_policies(supabase, campaign_id: str):
    """Ensure a couple of call policies exist for this campaign."""
    rows = [
        {
            "campaign_id": campaign_id,
            "status": "failed",
            "end_call_reason": "no_answer",
            "is_connected": False,
            "should_retry": True,
            "retry_sms": True,  # schedule SMS follow-up
            "first_retry_mins": 0,
            "next_retry_mins": 0,
            "max_retry_days": 1,
            "align_same_time": False,
        },
        {
            "campaign_id": campaign_id,
            "status": "completed",
            "end_call_reason": "completed",
            "is_connected": True,
            "should_retry": False,
            "retry_sms": False,
            "first_retry_mins": 0,
            "next_retry_mins": 0,
            "max_retry_days": 0,
            "align_same_time": False,
        },
    ]
    rest_upsert(
        "campaign_call_policies",
        rows,
        on_conflict="campaign_id,status,end_call_reason",
    )


def insert_call_log_stg(
    supabase,
    *,
    enrollment_id: str,
    contact_id: str,
    campaign_id: str,
    status: str = "failed",
    end_call_reason: str = "no_answer",
):
    now = datetime.now(timezone.utc)
    row = {
        "enrollment_id": enrollment_id,
        "contact_id": contact_id,
        "campaign_id": campaign_id,
        "type_of_call": "outbound",
        "call_id": f"call_{uuid.uuid4().hex}",
        "module_id": "sim-module",
        "duration_seconds": 12,
        "end_call_reason": end_call_reason,
        "executed_actions": {"actions": []},
        "prompt_variables": {},
        "recording_url": None,
        "transcript": "No answer.",
        "start_time_epoch_ms": int(now.timestamp() * 1000),
        "start_time": now.isoformat(),
        "agent": "pytest-bot",
        "timezone": "UTC",
        "phone_number_to": "+15550000000",
        "phone_number_from": "+15551112222",
        "status": status,
        "campaign_type": "live",
        "classification": None,
        "appointment_time": None,
        "processed": False,
    }
    rest_insert("phone_call_logs_stg", row)


# ---------- the e2e test ----------
@pytest.mark.e2e
def test_end_to_end_voice_then_sms(
    supabase,
    builder_funcs,
    enroll_funcs,
    orchestrator_funcs,
    call_processing_funcs,
    fake_contact,
    monkeypatch,
):
    # 0) Patch providers (no real network)
    try:
        import providers.sms as p_sms
        monkeypatch.setattr(p_sms, "send", sms_send, raising=True)
    except Exception:
        pass
    try:
        import providers.email as p_email
        monkeypatch.setattr(p_email, "send", email_send, raising=True)
    except Exception:
        pass
    try:
        import providers.voice as p_voice
        monkeypatch.setattr(p_voice, "place_call", voice_place_call, raising=True)
    except Exception:
        pass

    # 1) Seed org + contact
    org_id = ensure_org(supabase)
    contact_id = ensure_contact(supabase, org_id, fake_contact)

    # 2) Build a campaign (voice -> sms)
    create_campaign = builder_funcs["create_campaign"]
    add_step = builder_funcs["add_step"]

    campaign = create_campaign(
        name=f"pytest-campaign-{int(time.time())}",
        org_id=org_id,
        goal="lead_qualification",
    )
    assert campaign, "create_campaign should return dict or id"
    campaign_id = campaign["id"] if isinstance(campaign, dict) else campaign

    # Steps
    step1 = add_step(
        campaign_id=campaign_id,
        order_index=1,
        channel="voice",
        payload={"label": "Initial call", "script": "Hi, this is Cory from Admissions."},
        delay_minutes=0,
    )
    step2 = add_step(
        campaign_id=campaign_id,
        order_index=2,
        channel="sms",
        payload={
            "label": "Follow-up SMS",
            "body": "Sorry we missed you. Can we text you info?",
        },
        delay_minutes=2,
    )
    assert step1 and step2

    # Policies so the system knows what to do after a no_answer
    ensure_campaign_policies(supabase, campaign_id)

    # 3) Enroll contact through the agent (by details)
    enroll = enroll_funcs["enroll"]
    enrollment = enroll(
        campaign_id=campaign_id,
        contact_id=contact_id,  # <-- add this
        first_name=fake_contact["first_name"],
        last_name=fake_contact["last_name"],
        email=fake_contact["email"],
        phone=fake_contact["phone"],
    )
    assert enrollment
    enrollment_id = enrollment["id"] if isinstance(enrollment, dict) else enrollment

    # Make this enrollment due now (use REST to force schema headers)
    now = datetime.now(timezone.utc)
    rest_update_eq(
        "campaign_enrollments", "id", enrollment_id, {"next_run_at": now.isoformat()}
    )

    # 4) Orchestrator tick (should place a call)
    run_once = orchestrator_funcs["run_once"]
    res = run_once()
    if inspect.iscoroutine(res):
        asyncio.run(res)

    # Get fresh enrollment (should have current_step_id = step1)
    from tests.conftest import rest_single_by_id  # at top with other imports
    enr = rest_single_by_id("campaign_enrollments", enrollment_id)
    assert enr is not None and enr.get("current_step_id") is not None

    # 5) Simulate provider result in staging (no_answer) so call_processing can advance policy
    insert_call_log_stg(
        supabase,
        enrollment_id=enrollment_id,
        contact_id=enr["contact_id"],
        campaign_id=campaign_id,
        status="failed",
        end_call_reason="no_answer",
    )

    # 6) Process once (should log activity + schedule SMS)
    process_once = call_processing_funcs["process_once"]
    process_once()

    # 7) Assertions
    # 7a) At least one activity exists for this enrollment
    acts = (
        sb_table(supabase, "campaign_activities")
        .select("id, channel, status, scheduled_at")
        .eq("enrollment_id", enrollment_id)
        .execute()
        .data
    )
    assert isinstance(acts, list) and len(acts) >= 1

    # 7b) Either we scheduled an SMS (planned) or the enrollment progressed/finished
    sms_planned = [a for a in acts if a.get("channel") == "sms" and a.get("status") == "planned"]
    enr2 = (
        sb_table(supabase, "campaign_enrollments")
        .select("*")
        .eq("id", enrollment_id)
        .single()
        .execute()
        .data
    )
    assert enr2 is not None
    assert (len(sms_planned) >= 1) or (enr2.get("status") in ("completed", "inactive"))

