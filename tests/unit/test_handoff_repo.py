import os
from uuid import uuid4
import pytest
from dotenv import load_dotenv
from supabase import create_client, Client  # pip install supabase

pytestmark = pytest.mark.asyncio

# --- Load env & init client (HTTP via PostgREST) ------------------------------
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in .env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# Helpers
def _uuid():
    return str(uuid4())

async def _seed_org_user():
    return _uuid(), _uuid()

async def _rpc(name: str, params: dict):
    # supabase.rpc returns a Sync call; .execute() performs the HTTP request.
    # We keep tests async for consistency, but this call itself is sync.
    return supabase.rpc(name, params).execute()

async def _cleanup():
    # PostgREST requires a filter for DELETE; use a trivial one to delete all.
    # We filter on created_at >= '1970-01-01' to delete all rows.
    supabase.table("handoffs").delete().gte("created_at", "1970-01-01").execute()

@pytest.fixture(autouse=True)
async def _ensure_schema_and_cleanup():
    # Make sure the table exists by selecting 0 rows.
    # If it doesn't, PostgREST will return an error. Surface a helpful hint.
    try:
        supabase.table("handoffs").select("id").limit(1).execute()
    except Exception as e:
        raise AssertionError(
            "Table 'handoffs' not found via PostgREST. "
            "Apply your migrations (including handoffs table + RPC functions)."
        ) from e
    await _cleanup()
    yield
    await _cleanup()

# ------------------------------ Tests -----------------------------------------

async def test_create_idempotent_on_open():
    org_id, user_id = await _seed_org_user()
    lead_id = _uuid()

    # first create
    r1 = await _rpc("handoff_create", {
        "p_organization_id": org_id,
        "p_title": "Escalate to advisor",
        "p_task_type": "escalation",
        "p_source": "system",
        "p_source_key": f"lead:{lead_id}",
        "p_lead_id": lead_id,
        "p_description": "Price objection",
        "p_priority": "high",
        "p_assigned_to": None,
        "p_metadata": {},
        "p_explicit_sla_due_at": None
    })
    first = r1.data[0]

    # second create with same identity should return the same open/in_progress record
    r2 = await _rpc("handoff_create", {
        "p_organization_id": org_id,
        "p_title": "Escalate to advisor",
        "p_task_type": "escalation",
        "p_source": "system",
        "p_source_key": f"lead:{lead_id}",
        "p_lead_id": lead_id,
        "p_description": "Price objection",
        "p_priority": "high",
        "p_assigned_to": None,
        "p_metadata": {},
        "p_explicit_sla_due_at": None
    })
    second = r2.data[0]

    assert first["id"] == second["id"]
    assert first["status"] in ("open", "in_progress")
    assert first["sla_due_at"] is not None

async def test_mark_first_response_sets_timestamp_and_status():
    org_id, user_id = await _seed_org_user()

    rec = (await _rpc("handoff_create", {
        "p_organization_id": org_id,
        "p_title": "Callback",
        "p_task_type": "callback",
        "p_source": "system",
        "p_source_key": None,
        "p_lead_id": None,
        "p_description": None,
        "p_priority": "normal",
        "p_assigned_to": None,
        "p_metadata": {},
        "p_explicit_sla_due_at": None
    })).data[0]

    updated = (await _rpc("handoff_mark_first_response", {
        "p_handoff_id": rec["id"]
    })).data[0]

    assert updated["first_response_at"] is not None
    assert updated["status"] in ("in_progress", "resolved")

async def test_resolve_sets_snapshot_once_and_idempotent():
    org_id, user_id = await _seed_org_user()

    rec = (await _rpc("handoff_create", {
        "p_organization_id": org_id,
        "p_title": "Manual email",
        "p_task_type": "manual_email",
        "p_source": "system",
        "p_source_key": None,
        "p_lead_id": None,
        "p_description": None,
        "p_priority": "normal",
        "p_assigned_to": None,
        "p_metadata": {},
        "p_explicit_sla_due_at": None
    })).data[0]

    outcome1 = {"final_status": "emailed", "details": {"template": "admissions_followup"}}
    r1 = (await _rpc("handoff_resolve", {
        "p_handoff_id": rec["id"],
        "p_resolved_by": user_id,
        "p_resolution_note": "Done",
        "p_outcome_snapshot": outcome1
    })).data[0]
    assert r1["status"] == "resolved"
    ts = r1["resolved_at"]

    outcome2 = {"details": {"open_rate": 0.45}, "tags": ["A11-pass"]}
    r2 = (await _rpc("handoff_resolve", {
        "p_handoff_id": rec["id"],
        "p_resolved_by": user_id,
        "p_resolution_note": None,
        "p_outcome_snapshot": outcome2
    })).data[0]
    assert r2["status"] == "resolved"
    assert r2["resolved_at"] == ts
    assert r2["outcome_snapshot"]["final_status"] == "emailed"
    assert r2["outcome_snapshot"]["details"]["template"] == "admissions_followup"
    assert r2["outcome_snapshot"]["details"]["open_rate"] == 0.45
    assert "A11-pass" in r2["outcome_snapshot"]["tags"]
    assert r2["re_resolve_count"] >= 1

async def test_acceptance_A11_resolving_updates_outcome_snapshot():
    """A11: resolving updates outcome snapshot and repo behavior conforms."""
    org_id, user_id = await _seed_org_user()

    rec = (await _rpc("handoff_create", {
        "p_organization_id": org_id,
        "p_title": "Review conversation outcome",
        "p_task_type": "review_outcome",
        "p_source": "system",
        "p_source_key": None,
        "p_lead_id": None,
        "p_description": None,
        "p_priority": "normal",
        "p_assigned_to": None,
        "p_metadata": {"interaction_summary_id": _uuid()},
        "p_explicit_sla_due_at": None
    })).data[0]

    snap1 = {"outcome": "needs_more_info", "score": 0.62}
    r1 = (await _rpc("handoff_resolve", {
        "p_handoff_id": rec["id"],
        "p_resolved_by": user_id,
        "p_resolution_note": "Queued info email",
        "p_outcome_snapshot": snap1
    })).data[0]
    assert r1["status"] == "resolved"
    assert r1["outcome_snapshot"]["outcome"] == "needs_more_info"

    snap2 = {"outcome": "converted", "score": 0.91}
    r2 = (await _rpc("handoff_resolve", {
        "p_handoff_id": rec["id"],
        "p_resolved_by": user_id,
        "p_resolution_note": None,
        "p_outcome_snapshot": snap2
    })).data[0]
    assert r2["resolved_at"] == r1["resolved_at"]
    assert r2["outcome_snapshot"]["outcome"] == "converted"
    assert r2["outcome_snapshot"]["score"] == 0.91
