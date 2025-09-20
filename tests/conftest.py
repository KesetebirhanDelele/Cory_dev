# tests/conftest.py
import os
import sys
import json
import inspect
from pathlib import Path
from typing import Any, Callable
from datetime import datetime, timezone

import pytest
import requests
from dotenv import load_dotenv
from faker import Faker

# --- Ensure project root is importable (so imports like `import campaign_builder` work)
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --- Load env once for all tests
load_dotenv(dotenv_path=ROOT / ".env", override=False)

# --- Supabase client helper
try:
    from supabase import create_client, Client  # type: ignore
except Exception:  # pragma: no cover
    Client = Any  # type: ignore
    create_client = None  # type: ignore

SCHEMA = os.getenv("SUPABASE_SCHEMA", "dev_nexus")


def _require_service_role() -> str:
    """Tests must use Service Role to bypass RLS. Fail fast if missing."""
    srk = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    assert srk, (
        "SUPABASE_SERVICE_ROLE_KEY is not set.\n"
        "Set it in your .env from Supabase → Settings → API (Service role key)."
    )
    return srk


@pytest.fixture(scope="session")
def supabase() -> Any:
    url = os.environ["SUPABASE_URL"]
    key = _require_service_role()  # <-- force SRK (no anon fallback)
    assert create_client is not None, "Install supabase>=2.4 (pip install supabase)"
    client: Any = create_client(url, key)
    # Pin schema so PostgREST sends Accept-Profile & Content-Profile headers
    try:
        client.postgrest.schema = SCHEMA  # type: ignore[attr-defined]
        # also ensure headers (belt & suspenders)
        client.postgrest.headers["Accept-Profile"] = SCHEMA
        client.postgrest.headers["Content-Profile"] = SCHEMA
    except Exception:
        pass
    return client

def sb_table(client: Any, name: str):
    try:
        client.postgrest.schema = SCHEMA
        h = client.postgrest.headers
        h["Accept-Profile"] = SCHEMA
        h["Content-Profile"] = SCHEMA
    except Exception:
        pass
    # Force schema on every call (works on supabase>=2.4)
    try:
        return client.table(name, schema=SCHEMA)
    except TypeError:
        return client.table(name)

class _SchemaPinnedClient:
    """Wrap a Supabase client so every call uses the given schema, and
    force PostgREST headers so reads/writes never fall back to 'public'."""
    def __init__(self, client, schema: str):
        self._c = client
        self._schema = schema
        self._pin_headers()

    def _pin_headers(self):
        try:
            self._c.postgrest.schema = self._schema
            h = self._c.postgrest.headers
            h["Accept-Profile"] = self._schema
            h["Content-Profile"] = self._schema
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._c, name)

    def table(self, name, *args, **kwargs):
        self._pin_headers()
        try:
            return self._c.table(name, schema=self._schema)  # supabase>=2.4
        except TypeError:
            return self._c.table(name)

    # alias used by older code
    def from_(self, name, *args, **kwargs):
        return self.table(name, *args, **kwargs)


# --- RAW REST helpers (force schema headers on every request for WRITES/READS)
def _rest_headers() -> dict:
    srk = _require_service_role()
    return {
        "apikey": srk,
        "Authorization": f"Bearer {srk}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
        "Accept-Profile": SCHEMA,   # read
        "Content-Profile": SCHEMA,  # write
    }


def _rest_url(table: str) -> str:
    return os.environ["SUPABASE_URL"].rstrip("/") + f"/rest/v1/{table}"


def rest_get(table: str, params: dict) -> list[dict]:
    r = requests.get(_rest_url(table), headers=_rest_headers(), params=params)
    if not r.ok:
        raise AssertionError(f"REST get {table} failed {r.status_code}: {r.text}")
    return r.json() if r.text else []


def rest_single_by_id(table: str, id_: str) -> dict | None:
    rows = rest_get(table, {"select": "*", "id": f"eq.{id_}", "limit": "1"})
    return rows[0] if rows else None


def rest_insert(table: str, rows: dict | list[dict]) -> list[dict]:
    r = requests.post(_rest_url(table), headers=_rest_headers(), data=json.dumps(rows))
    if not r.ok:
        raise AssertionError(f"REST insert {table} failed {r.status_code}: {r.text}")
    return r.json() if r.text else []


def rest_upsert(table: str, rows: list[dict], on_conflict: str) -> list[dict]:
    headers = _rest_headers() | {"Prefer": "return=representation,resolution=merge-duplicates"}
    params = {"on_conflict": on_conflict}
    r = requests.post(_rest_url(table), headers=headers, params=params, data=json.dumps(rows))
    if not r.ok:
        raise AssertionError(f"REST upsert {table} failed {r.status_code}: {r.text}")
    return r.json() if r.text else []


def rest_update_eq(table: str, key: str, value: str, updates: dict) -> list[dict]:
    headers = _rest_headers() | {"Prefer": "return=representation"}
    params = {key: f"eq.{value}"}
    r = requests.patch(_rest_url(table), headers=headers, params=params, data=json.dumps(updates))
    if not r.ok:
        raise AssertionError(f"REST update {table} failed {r.status_code}: {r.text}")
    return r.json() if r.text else []


# --- tolerant getter ---
def _get_fn(mod, *names: str) -> Callable:
    for n in names:
        if hasattr(mod, n):
            return getattr(mod, n)
    raise AttributeError(f"Expected one of {names} on {mod.__name__}")


# --- Resolve org/goal ONLY from organizations (or .env) ---
def resolve_org_and_goal(sb: Any):
    org_id = os.getenv("ORG_ID")
    goal = os.getenv("CAMPAIGN_GOAL", "lead_qualification")

    if not org_id:
        # Read first org id (no writes here; some org schemas have extra NOT NULLs)
        res = sb_table(sb, "organizations").select("id").limit(1).execute().data
        if isinstance(res, list) and res:
            org_id = res[0]["id"]

    assert org_id, (
        f"No organization found in schema '{SCHEMA}'. "
        f"Either set ORG_ID in .env or insert a row into {SCHEMA}.organizations."
    )
    return org_id, goal


# --- Builder adapters ---
@pytest.fixture(scope="session")
def builder_funcs(supabase):
    import campaign_builder as cb
    create_fn = _get_fn(cb, "create_campaign", "create_or_update_campaign")
    # We write steps directly to campaign_steps via REST to stay schema-safe.

    def create_campaign(name, description=None, metadata=None, org_id=None, goal=None):
        if not org_id or not goal:
            _org, _goal = resolve_org_and_goal(supabase)
            org_id = org_id or _org
            goal = goal or _goal

        params = set(inspect.signature(create_fn).parameters)
        kwargs = {}

        # required name
        if "name" in params:
            kwargs["name"] = name
        elif "campaign_name" in params:
            kwargs["campaign_name"] = name
        else:
            try:
                return create_fn(name)  # positional fallback
            except TypeError:
                return create_fn()

        # only pass accepted fields
        if description is not None and "description" in params:
            kwargs["description"] = description
        if metadata is not None and "metadata" in params:
            kwargs["metadata"] = metadata
        if org_id is not None and "org_id" in params:
            kwargs["org_id"] = org_id
        if goal is not None and "goal" in params:
            kwargs["goal"] = goal

        return create_fn(**kwargs)

    def add_step(*, campaign_id, order_index=1, channel="voice", payload=None, delay_minutes=0):
        """
        Insert into dev_nexus.campaign_steps via REST.
        Maps:
          order_index -> order_id
          delay_minutes -> wait_before_ms
          payload -> metadata (keeps script/body/subject/html safely)
        """
        payload = payload or {}
        row = {
            "campaign_id": campaign_id,
            "order_id": int(order_index),
            "channel": channel,
            "wait_before_ms": int(delay_minutes * 60 * 1000),
        }
        # Optional label & metadata
        label = payload.get("label")
        if label:
            row["label"] = str(label)

        meta = {k: v for k, v in payload.items() if k != "label"}
        if meta:
            row["metadata"] = meta

        # Insert and return id (via REST to ensure Content-Profile header)
        resp = rest_insert("campaign_steps", row)
        return resp[0]["id"] if isinstance(resp, list) and resp else None

    return dict(create_campaign=create_campaign, add_step=add_step)


# --- Enrollment adapter (schema-safe; doesn’t rely on product code using `public`) ---
@pytest.fixture(scope="session")
def enroll_funcs(supabase):
    pinned_sb = _SchemaPinnedClient(supabase, SCHEMA)

    def _ensure_contact_id(org_id: str, provided: dict) -> str:
        if provided.get("contact_id"):
            return provided["contact_id"]
        first = provided.get("first_name") or "Test"
        last = provided.get("last_name") or "User"
        row = {
            "org_id": org_id,
            "first_name": first,
            "last_name": last,
            "full_name": f"{first} {last}",
            "email": provided.get("email"),
            "phone": provided.get("phone"),
        }
        created = rest_insert("contacts", row)
        assert created and created[0].get("id"), "Failed to create contact"
        return created[0]["id"]

    def enroll(**kwargs):
        provided = dict(kwargs)
        org_id, _ = resolve_org_and_goal(pinned_sb)

        campaign_id = provided["campaign_id"]
        contact_id = _ensure_contact_id(org_id, provided)

        # Use REST (forces dev_nexus schema) rather than sb_table(...)
        steps = rest_get(
            "campaign_steps",
            {
                "select": "id,channel,order_id",
                "campaign_id": f"eq.{campaign_id}",
                "order": "order_id.asc",
                "limit": "1",
            },
        )
        next_channel = steps[0]["channel"] if steps else "voice"

        row = {
            "org_id": org_id,
            "contact_id": contact_id,
            "campaign_id": campaign_id,
            "status": "active",
            "next_channel": next_channel,
            "next_run_at": datetime.now(timezone.utc).isoformat(),
        }
        created = rest_insert("campaign_enrollments", row)
        assert created and created[0].get("id"), "Failed to create enrollment"
        return created[0]

    return dict(enroll=enroll)

# --- Orchestrator adapter --
# tests/conftest.py
@pytest.fixture(scope="session")
def orchestrator_funcs():
    import orchestrator_loop as loop
    # IMPORTANT: prefer a one-shot function first
    run_once = _get_fn(loop, "tick", "run_once", "tick_once", "main")
    return dict(run_once=run_once)

# --- Call-processing adapter ---
# --- Call-processing adapter (force module to use the test schema) ---
@pytest.fixture(scope="session")
def call_processing_funcs(supabase):
    import call_processing_agent as cpa
    pinned = _SchemaPinnedClient(supabase, SCHEMA)

    # 1) Point every likely handle at the pinned client
    cpa.sb = pinned
    if hasattr(cpa, "db"):
        cpa.db = pinned  # some modules alias the client as `db`

    # 2) If the module lazily creates a new client, neuter that
    try:
        import supabase as _supabase_pkg
        def _return_pinned(*args, **kwargs):
            return pinned
        # If the module keeps a reference to `create_client`, override it there
        if hasattr(cpa, "create_client"):
            cpa.create_client = _return_pinned
        # And as a belt-and-suspenders, override the package symbol it might import from
        if hasattr(_supabase_pkg, "create_client"):
            # do NOT globally monkeypatch; only override where used:
            pass
    except Exception:
        pass

    # 3) Make sure headers stay pinned before each request
    try:
        h = pinned.postgrest.headers
        h["Accept-Profile"]  = SCHEMA
        h["Content-Profile"] = SCHEMA
    except Exception:
        pass

    # 4) Hand back the right entrypoint
    return dict(process_once=_get_fn(cpa, "process_once", "run_once", "run_call_processing_once"))

# --- Test utilities ---
@pytest.fixture()
def fake_contact():
    f = Faker()
    return dict(
        first_name=f.first_name(),
        last_name=f.last_name(),
        email=f.unique.email(),
        phone="+1555" + f.msisdn()[:7],
    )


@pytest.fixture(autouse=True)
def set_test_mode(monkeypatch):
    # Make product code run in test/simulated mode when possible
    monkeypatch.setenv("TEST_MODE", "true")
    monkeypatch.setenv("SIMULATE_PROVIDERS", "true")

    # Avoid nested asyncio.run() inside sms_sender during orchestrator tests
    try:
        import sms_sender
        monkeypatch.setattr(sms_sender, "run_sms_sender", lambda: None, raising=True)
    except Exception:
        pass

    # Provide supabase_repo.now_iso if product code imports it
    try:
        import supabase_repo as sr
        if not hasattr(sr, "now_iso"):
            monkeypatch.setattr(sr, "now_iso", lambda: datetime.now(timezone.utc).isoformat(), raising=False)
    except Exception:
        pass

    yield


# --- Light sanity check (READ-only) to confirm schema is exposed ---
@pytest.fixture(scope="session", autouse=True)
def verify_schema_access(supabase):
    sb_table(supabase, "organizations").select("id").limit(1).execute()
