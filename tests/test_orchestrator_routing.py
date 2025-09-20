import pytest
from datetime import datetime, timedelta, timezone
import uuid

from tests.conftest import sb_table, rest_update_eq, rest_insert  # rest_insert used in ensure_org
from tests.conftest import sb_table, rest_update_eq, rest_get  # add rest_get

def ensure_org(supabase) -> str:
    """Return an existing org id or create a minimal one (schema-safe)."""
    res = sb_table(supabase, "organizations").select("id").limit(1).execute().data
    if isinstance(res, list) and res:
        return res[0]["id"]

    created = rest_insert("organizations", {
        "name": "Pytest Org",
        "slug": f"pytest-org-{uuid.uuid4().hex[:8]}",
    })
    return created[0]["id"]


@pytest.mark.e2e
def test_due_actions_view_has_rows_after_enroll(supabase, fake_contact, builder_funcs, enroll_funcs):
    org_id = ensure_org(supabase)

    create_campaign = builder_funcs["create_campaign"]
    add_step = builder_funcs["add_step"]
    enroll = enroll_funcs["enroll"]

    # 1) Campaign with a voice first step
    c = create_campaign(name="pytest-routing", org_id=org_id, goal="lead_qualification")
    cid = c["id"] if isinstance(c, dict) else c
    s1 = add_step(
        campaign_id=cid,
        order_index=1,
        channel="voice",
        payload={"label": "Intro call", "script": "Hello"},
        delay_minutes=0,
    )
    assert s1

    # 2) Enroll contact
    e = enroll(
        campaign_id=cid,
        first_name=fake_contact["first_name"],
        last_name=fake_contact["last_name"],
        email=fake_contact["email"],
        phone=fake_contact["phone"],
    )
    eid = e["id"] if isinstance(e, dict) else e

    # 3) Make this enrollment due now (use REST to avoid datetime JSON issues)
    due_time = (datetime.now(timezone.utc) - timedelta(seconds=1)).replace(microsecond=0)
    rest_update_eq("campaign_enrollments", "id", eid, {"next_run_at": due_time.isoformat()})

    # 4) Confirm it shows up in the due view
    due = rest_get(
    "v_due_actions",
    {"select": "*", "enrollment_id": f"eq.{eid}", "limit": "1"}
)
    assert isinstance(due, list) and len(due) == 1

    # Optional: verify channel is voice (since first step is voice)
    assert due[0].get("next_channel") == "voice"
