# tests/conftest.py
# --- Windows: ensure a selector loop (more compatible with asyncpg DNS resolution)
import sys
import asyncio

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import os
import json
import inspect
from pathlib import Path
from typing import Any, Callable
from datetime import datetime, timezone
import contextlib

import pytest
import pytest_asyncio
import requests
from dotenv import load_dotenv
from faker import Faker
import asyncpg

# --------------------------------------------------------------------------------------
# Early guard: prevent nested asyncio.run() even if used at import-time by product code.
# (Fixtures run after imports; this hook runs before tests collect/import.)
# --------------------------------------------------------------------------------------
def pytest_sessionstart(session):
    import asyncio as _asyncio
    def _oops(*a, **k):
        raise RuntimeError("asyncio.run() should not be called at import time in tests")
    _asyncio.run = _oops  # type: ignore[attr-defined]

# --- Ensure project root is importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --- Load env once for all tests
load_dotenv(dotenv_path=ROOT / ".env", override=False)

SCHEMA = (os.getenv("DB_SCHEMA") or "dev_nexus").strip() or "dev_nexus"

# 🔒 Guard during test execution: if any code calls asyncio.run(), fail fast.
@pytest.fixture(autouse=True)
def _ban_nested_asyncio_run(monkeypatch):
    import asyncio as _asyncio
    def _oops(*a, **k):
        raise RuntimeError("asyncio.run() should not be called from within tests")
    monkeypatch.setattr(_asyncio, "run", _oops, raising=True)

# --- Build a proper Postgres DSN (don’t mix API URL/password)
from urllib.parse import urlparse, quote_plus

def _pg_dsn() -> str:
    # Allow an override if you ever set a full DATABASE_URL
    db_url = (os.getenv("DATABASE_URL") or "").strip()
    if db_url.startswith(("postgres://", "postgresql://")):
        return db_url

    supa_url = (os.getenv("SUPABASE_URL") or "").strip()
    db_pw    = (os.getenv("SUPABASE_DATABASE_PASSWORD") or "").strip()

    assert supa_url and db_pw, (
        "Set SUPABASE_URL and SUPABASE_DATABASE_PASSWORD in .env "
        "(or provide a full DATABASE_URL)."
    )

    host = urlparse(supa_url).hostname or ""
    project_ref = host.split(".")[0] if host else ""
    db_host = f"db.{project_ref}.supabase.co" if project_ref else host

    # Supabase Postgres defaults
    user = (os.getenv("PGUSER") or "postgres").strip() or "postgres"
    db   = (os.getenv("PGDATABASE") or "postgres").strip() or "postgres"

    # Quote creds; require SSL
    return f"postgresql://{quote_plus(user)}:{quote_plus(db_pw)}@{db_host}:5432/{db}?sslmode=require"

# ---------- Loop-proof “DirectPool” (fresh connection per acquire) ----------
class _DirectConnCtx:
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._conn = None
    async def __aenter__(self):
        # connection is created on the CURRENT running loop
        self._conn = await asyncpg.connect(self._dsn)
        return self._conn
    async def __aexit__(self, exc_type, exc, tb):
        with contextlib.suppress(Exception):
            await self._conn.close()

class _DirectPool:
    def __init__(self, dsn: str):
        self._dsn = dsn
    def acquire(self, *_a, **_k):
        return _DirectConnCtx(self._dsn)
    async def close(self):
        return

# ✅ Use pytest-asyncio’s fixture so the pool is created on the test’s loop.
# Keep function scope to avoid cross-loop reuse.
@pytest_asyncio.fixture(scope="function")
async def asyncpg_pool():
    dsn = _pg_dsn()
    print("** using DIRECT POOL fixture **", dsn)  # debug line (keep for now)
    pool = _DirectPool(dsn)
    try:
        yield pool
    finally:
        await pool.close()

# --- Supabase client helper
try:
    from supabase import create_client, Client  # type: ignore
except Exception:  # pragma: no cover
    Client = Any  # type: ignore
    create_client = None  # type: ignore

def _require_service_role() -> str:
    srk = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    assert srk, (
        "SUPABASE_SERVICE_ROLE_KEY is not set.\n"
        "Set it in your .env from Supabase → Settings → API (Service role key)."
    )
    return srk

@pytest.fixture(scope="session")
def supabase() -> Any:
    url = os.environ["SUPABASE_URL"]
    key = _require_service_role()
    assert create_client is not None, "Install supabase>=2.4 (pip install supabase)"
    client: Any = create_client(url, key)
    try:
        client.postgrest.schema = SCHEMA  # type: ignore[attr-defined]
        client.postgrest.headers["Accept-Profile"]  = SCHEMA
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
    try:
        return client.table(name, schema=SCHEMA)  # supabase >= 2.4 supports schema kw
    except TypeError:
        return client.table(name)

class _SchemaPinnedClient:
    """Wrap a Supabase client so every call uses the given schema,
    forcing PostgREST headers to avoid falling back to 'public'."""
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
    def table(self, name: str, *args, **kwargs):
        self._pin_headers()
        try:
            return self._c.table(name, schema=self._schema)
        except TypeError:
            return self._c.table(name)
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
    import app.agents.campaign_builder as cb
    create_fn = _get_fn(cb, "create_campaign", "create_or_update_campaign")

    def create_campaign(name, description=None, metadata=None, org_id=None, goal=None):
        if not org_id or not goal:
            _org, _goal = resolve_org_and_goal(supabase)
            org_id = org_id or _org
            goal = goal or _goal

        params = set(inspect.signature(create_fn).parameters)
        kwargs = {}

        if "name" in params:
            kwargs["name"] = name
        elif "campaign_name" in params:
            kwargs["campaign_name"] = name
        else:
            try:
                return create_fn(name)  # positional fallback
            except TypeError:
                return create_fn()

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
        payload = payload or {}
        row = {
            "campaign_id": campaign_id,
            "order_id": int(order_index),
            "channel": channel,
            "wait_before_ms": int(delay_minutes * 60 * 1000),
        }
        label = payload.get("label")
        if label:
            row["label"] = str(label)
        meta = {k: v for k, v in payload.items() if k != "label"}
        if meta:
            row["metadata"] = meta
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

        steps = rest_get(
            "campaign_steps",
            {
                "select": "id,channel,order_id",
                "campaign_id": f"eq.{campaign_id}",
            } | {"order": "order_id.asc", "limit": 1}
        )
        first_step_id = steps[0]["id"] if steps else None
        next_channel = steps[0]["channel"] if steps else "voice"

        now = datetime.now(timezone.utc)
        row = {
            "org_id": org_id,
            "contact_id": contact_id,
            "campaign_id": campaign_id,
            "status": "active",
            "current_step_id": first_step_id,
            "next_channel": next_channel,
            "next_run_at": now.isoformat(),
            "started_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        created = rest_insert("campaign_enrollments", row)
        assert created and created[0].get("id"), "Failed to create enrollment"
        return created[0]

    return dict(enroll=enroll)

# --- Orchestrator adapter ---
@pytest.fixture(scope="session")
def orchestrator_funcs():
    import app.orchestrator.loop as loop
    run_once = _get_fn(loop, "tick", "run_once", "tick_once", "main")
    return dict(run_once=run_once)

# --- Call-processing adapter (force module to use the test schema) ---
@pytest.fixture(scope="session")
def call_processing_funcs(supabase):
    import app.agents.call_processing_agent as cpa
    pinned = _SchemaPinnedClient(supabase, SCHEMA)
    cpa.sb = pinned
    if hasattr(cpa, "db"):
        cpa.db = pinned
    try:
        import supabase as _supabase_pkg  # noqa: F401
        def _return_pinned(*args, **kwargs):
            return pinned
        if hasattr(cpa, "create_client"):
            cpa.create_client = _return_pinned
    except Exception:
        pass
    try:
        h = pinned.postgrest.headers
        h["Accept-Profile"]  = SCHEMA
        h["Content-Profile"] = SCHEMA
    except Exception:
        pass
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
    monkeypatch.setenv("TEST_MODE", "true")
    monkeypatch.setenv("SIMULATE_PROVIDERS", "true")
    try:
        from app.channels import sms_sender
        monkeypatch.setattr(sms_sender, "run_sms_sender", lambda: None, raising=True)
    except Exception:
        pass
    try:
        import app.data.supabase_repo as sr
        if not hasattr(sr, "now_iso"):
            monkeypatch.setattr(sr, "now_iso", lambda: datetime.now(timezone.utc).isoformat(), raising=False)
    except Exception:
        pass
    yield

# --- Light sanity check (READ-only) to confirm schema is exposed ---
@pytest.fixture(scope="session", autouse=True)
def verify_schema_access(supabase):
    sb_table(supabase, "organizations").select("id").limit(1).execute()
