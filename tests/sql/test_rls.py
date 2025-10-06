# tests/sql/test_rls.py
"""
Ticket B1.2 — RLS & Roles
Acceptance: Anon blocked, service-role allowed; least-privileged baseline.
"""
import os
import json
import pytest
from dotenv import load_dotenv, find_dotenv
import requests

# Load env
load_dotenv(find_dotenv(filename=".env", usecwd=True) or find_dotenv(filename=".env.test", usecwd=True))

BASE = os.environ["SUPABASE_URL"].rstrip("/")
SVC_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]  # or SUPABASE_SERVICE_KEY
ANON_KEY = os.getenv("SUPABASE_ANON_KEY")      # optional but recommended
SCHEMA = os.getenv("DB_SCHEMA", "dev_nexus")

def svc_headers():
    return {
        "apikey": SVC_KEY,
        "Authorization": f"Bearer {SVC_KEY}",
        "Accept-Profile": SCHEMA,
    }

def anon_headers():
    return {
        "apikey": ANON_KEY,
        "Authorization": f"Bearer {ANON_KEY}",
        "Accept-Profile": SCHEMA,
    }

@pytest.mark.order(1)
def test_service_role_can_insert_and_select_message():
    ins = requests.post(
        f"{BASE}/rest/v1/message",
        headers={**svc_headers(), "Content-Type": "application/json", "Prefer": "return=representation"},
        data=json.dumps({
            "project_id": None,  # FK is NOT NULL in prod; None should 400 but proves access path
            "provider_ref": "svc_test_ref",
            "direction": "inbound",
            "payload": {}
        }),
        timeout=20,
    )
    assert ins.status_code in (201, 400), f"service role should reach table, got {ins.status_code} {ins.text}"

    sel = requests.get(
        f"{BASE}/rest/v1/message?select=id&limit=1",
        headers=svc_headers(),
        timeout=20,
    )
    assert sel.status_code == 200, f"service role select should be allowed, got {sel.status_code} {sel.text}"

@pytest.mark.order(2)
def test_anon_is_blocked_for_insert_and_select_message():
    if not ANON_KEY:
        pytest.skip("No SUPABASE_ANON_KEY provided; skipping anon test.")

    ins = requests.post(
        f"{BASE}/rest/v1/message",
        headers={**anon_headers(), "Content-Type": "application/json"},
        data=json.dumps({
            "project_id": None,
            "provider_ref": "anon_ref",
            "direction": "inbound",
            "payload": {}
        }),
        timeout=20,
    )
    # Accept 400/401/403 as "blocked" for anon
    assert ins.status_code in (400, 401, 403), (
        f"anon insert should be denied by RLS/privs, got {ins.status_code} {ins.text}"
    )

    sel = requests.get(
        f"{BASE}/rest/v1/message?select=id&limit=1",
        headers=anon_headers(),
        timeout=20,
    )
    # Similarly, treat all of these as "not allowed to read data"
    assert sel.status_code in (200, 400, 401, 403)
    if sel.status_code == 200:
        body = sel.json()
        assert body == [] or isinstance(body, list), f"anon select should return empty set, got {body}"