# tests/sql/test_telemetry_view.py
# Pytest for B2.1 — Append-Only Telemetry View (Supabase cloud friendly)

import os, re, sys, urllib.parse, asyncio
from uuid import uuid4
from datetime import datetime, timezone, timedelta

import asyncpg
import pytest
from dotenv import load_dotenv

# --- Windows event-loop fix (early) ---
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

load_dotenv()
pytestmark = pytest.mark.asyncio  # let pytest-asyncio manage the loop

# ---------------- DSN builder (unused here, but kept for local smoke tests) ----------------
def _dsn_from_env() -> str:
    db_url = (os.getenv("SUPABASE_URL") or "").strip()
    if db_url.startswith(("postgres://", "postgresql://")):
        return db_url
    supabase_url = (os.getenv("SUPABASE_URL") or "").strip()
    db_password  = (os.getenv("SUPABASE_DATABASE_PASSWORD") or "").strip()
    if supabase_url and db_password:
        host = urllib.parse.urlparse(supabase_url).hostname or ""
        if host.endswith(".supabase.co"):
            project_ref = host.split(".")[0]
            db_host = f"db.{project_ref}.supabase.co"
            return (
                f"postgresql://postgres:{urllib.parse.quote_plus(db_password)}"
                f"@{db_host}:5432/postgres?sslmode=require"
            )
    raise RuntimeError(
        "Set SUPABASE_URL or set SUPABASE_URL and SUPABASE_DATABASE_PASSWORD in .env."
    )

# ---------------- schema helper ----------------
def _schema_from_env() -> str:
    schema = (os.getenv("SUPABASE_SCHEMA") or "dev_nexus").strip() or "dev_nexus"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        raise ValueError(f"Invalid SUPABASE_SCHEMA {schema!r}.")
    return schema

SCHEMA = _schema_from_env()

# ---------------- seed helpers ----------------
async def _ensure_parents(conn, project_id, provider_id):
    async with conn.transaction():
        await conn.execute(
            "SELECT set_config('request.jwt.claims', '{\"role\":\"service_role\"}', true);"
        )

        tenant_id = uuid4()
        # avoid name collisions if there is a unique index on tenant.name
        tenant_name = f"Seed Tenant {project_id}"

        await conn.execute(
            f"INSERT INTO {SCHEMA}.tenant (id, name) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
            tenant_id, tenant_name
        )

        await conn.execute(
            f"INSERT INTO {SCHEMA}.project (id, tenant_id, name) VALUES ($1, $2, 'Seed Project') ON CONFLICT (id) DO NOTHING",
            project_id, tenant_id
        )

        # 👇 unique provider name so we never clash with other tests
        provider_name = f"SeedProvider-{provider_id}"  # unique per run
        await conn.execute(
            f"insert into {SCHEMA}.providers (id, name) values ($1, $2) on conflict (id) do nothing",
            provider_id, provider_name
        )

async def seed_minimum(conn: asyncpg.Connection):
    project_id  = uuid4()
    provider_id = uuid4()

    async with conn.transaction():
        await _ensure_parents(conn, project_id, provider_id)

        t0 = datetime.now(timezone.utc) - timedelta(minutes=5)
        t1 = datetime.now(timezone.utc) - timedelta(minutes=4)

        await conn.execute(
            f"""
            INSERT INTO {SCHEMA}.message
                (id, project_id, provider_id, provider_ref, direction, payload, created_at)
            VALUES (gen_random_uuid(), $1, $2, 'ref-msg-1', 'outbound', '{{}}'::jsonb, $3)
            """,
            project_id, provider_id, t0
        )

        await conn.execute(
            f"""
            INSERT INTO {SCHEMA}.event
                (id, project_id, provider_id, provider_ref, direction, type, data, created_at)
            VALUES (gen_random_uuid(), $1, $2, 'ref-evt-1', 'outbound', 'classification', '{{}}'::jsonb, $3)
            """,
            project_id, provider_id, t1
        )

    return project_id

# ---------------- tests ----------------
async def test_ordering_and_projection(asyncpg_pool):
    # Assert we’re using the direct pool (no background tasks / no loop crossing)
    from tests.conftest import _DirectPool
    assert isinstance(asyncpg_pool, _DirectPool)

    async with asyncpg_pool.acquire() as conn:
        project_id = await seed_minimum(conn)
        rows = await conn.fetch(
            "SELECT * FROM telemetry_timeline($1, '-infinity'::timestamptz, 'infinity'::timestamptz, 100)",
            project_id,
        )

        assert len(rows) >= 2
        for i in range(len(rows) - 1):
            a, b = rows[i], rows[i + 1]
            assert (a["occurred_at"] < b["occurred_at"]) or (
                a["occurred_at"] == b["occurred_at"] and a["event_pk"] <= b["event_pk"]
            )
        r = rows[0]
        assert set(r.keys()) == {
            "occurred_at", "event_pk", "event_kind", "project_id",
            "provider_id", "provider_ref", "direction", "payload",
        }

async def test_view_is_append_only(asyncpg_pool):
    from tests.conftest import _DirectPool
    assert isinstance(asyncpg_pool, _DirectPool)

    async with asyncpg_pool.acquire() as conn:
        with pytest.raises(asyncpg.PostgresError):
            await conn.execute("""UPDATE telemetry_view SET payload = payload || '{"x":1}'::jsonb""")
        with pytest.raises(asyncpg.PostgresError):
            await conn.execute("DELETE FROM telemetry_view")
        with pytest.raises(asyncpg.PostgresError):
            await conn.execute(
                """
                INSERT INTO telemetry_view(occurred_at, event_pk, event_kind, project_id, provider_id, provider_ref, direction, payload)
                VALUES (now(), gen_random_uuid(), 'message', gen_random_uuid(), gen_random_uuid(), 'x', 'outbound', '{}'::jsonb)
                """
            )
