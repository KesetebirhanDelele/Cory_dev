import pytest
from datetime import datetime, timezone
import uuid

from tests.conftest import sb_table
from tests.conftest import rest_update_eq  # add import at top

now = datetime.now(timezone.utc)

def ensure_org(supabase) -> str:
    res = sb_table(supabase, "organizations").select("id").limit(1).execute().data
    if isinstance(res, list) and res:
        return res[0]["id"]
    ins = sb_table(supabase, "organizations").insert({
        "name": "Pytest Org",
        "slug": f"pytest-org-{uuid.uuid4().hex[:8]}",
    }).execute().data
    return ins[0]["id"]

@pytest.mark.e2e
def test_due_actions_view_has_rows_after_enroll(supabase, fake_contact, builder_funcs, enroll_funcs):
    org_id = ensure_org(supabase)

    create_campaign = builder_funcs["create_campaign"]
    add_step = builder_funcs["add_step"]
    enroll = enroll_funcs["enroll"]

    # campaign with voice first step
    c = create_campaign(name="pytest-routing", org_id=org_id, goal="lead_qualification")
    cid = c["id"] if isinstance(c, dict) else c
    s1 = add_step(campaign_id=cid, order_index=1, channel="voice",
                  payload={"label": "Intro call", "script": "Hello"}, delay_minutes=0)
    assert s1

    # enroll; due now
    e = enroll(campaign_id=cid,
               first_name=fake_contact["first_name"],
               last_name=fake_contact["last_name"],
               email=fake_contact["email"],
               phone=fake_contact["phone"])
    eid = e["id"] if isinstance(e, dict) else e

    now = datetime.now(timezone.utc)
    rest_update_eq("campaign_enrollments", "id", eid, {"next_run_at": now.isoformat()})
    sb_table(supabase, "campaign_enrollments").update({"next_run_at": now}).eq("id", eid).execute()
    # ensure it appears in due view
    due = sb_table(supabase, "v_due_actions").select("*").eq("enrollment_id", eid).limit(1).execute().data
    assert isinstance(due, list) and len(due) == 1

