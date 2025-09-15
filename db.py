# db.py (asyncpg-only, clean)
import os
import asyncpg
from typing import Any, Dict, List

_DSN = os.environ["DATABASE_URL"]  # Supabase Postgres connection string

_pool: asyncpg.Pool | None = None

async def init_db_pool():
    """Call once on startup."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=_DSN, min_size=1, max_size=5)

def _pool_required():
    if _pool is None:
        raise RuntimeError("Call init_db_pool() before using db functions.")
    return _pool

# ---------- Reads ----------

async def fetch_due_actions() -> List[Dict[str, Any]]:
    """
    Reads from a VIEW you created that lists enrollments whose next action is due.
    Make sure the view name & schema match your DB.
    """
    sql = """
    select *
    from dev_nexus.v_due_actions
    order by next_run_at nulls last
    """
    pool = _pool_required()
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql)
        return [dict(r) for r in rows]

async def fetch_due_sms() -> List[Dict[str, Any]]:
    """
    Pull planned SMS that are due to send now.
    """
    sql = """
    select
        a.id   as activity_id,
        a.org_id,
        a.enrollment_id,
        a.generated_message
    from dev_nexus.campaign_activities a
    join dev_nexus.campaign_enrollments e on e.id = a.enrollment_id
    where a.channel = 'sms'
      and a.status  = 'planned'
      and a.scheduled_at <= now()
    order by a.scheduled_at asc
    """
    pool = _pool_required()
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql)
        return [dict(r) for r in rows]

# ---------- Writes ----------

async def insert_activity(activity: Dict[str, Any]) -> Dict[str, Any]:
    """
    Dynamic insert into dev_nexus.campaign_activities.
    Returns the inserted row (at least the id).
    """
    cols = list(activity.keys())
    vals = [activity[c] for c in cols]
    placeholders = [f"${i}" for i in range(1, len(cols) + 1)]
    sql = f"""
      insert into dev_nexus.campaign_activities ({', '.join(cols)})
      values ({', '.join(placeholders)})
      returning id
    """
    pool = _pool_required()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *vals)
        return {"id": row["id"]}

async def update_activity(activity_id, patch: Dict[str, Any]) -> None:
    """
    Partial update by id.
    """
    if not patch:
        return
    sets = []
    vals = []
    i = 1
    for k, v in patch.items():
        sets.append(f"{k} = ${i}")
        vals.append(v)
        i += 1
    vals.append(activity_id)
    sql = f"""
      update dev_nexus.campaign_activities
         set {', '.join(sets)}
       where id = ${i}
    """
    pool = _pool_required()
    async with pool.acquire() as conn:
        await conn.execute(sql, *vals)

async def upsert_staging(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Upsert into phone_call_logs_stg by call_id (adjust if your constraint differs).
    """
    cols = list(row.keys())
    vals = [row[c] for c in cols]
    placeholders = [f"${i}" for i in range(1, len(cols) + 1)]
    updates = ", ".join([f"{c}=excluded.{c}" for c in cols if c != "id"])

    sql = f"""
      insert into dev_nexus.phone_call_logs_stg ({', '.join(cols)})
      values ({', '.join(placeholders)})
      on conflict (call_id) do update
         set {updates}
      returning id
    """
    pool = _pool_required()
    async with pool.acquire() as conn:
        rec = await conn.fetchrow(sql, *vals)
        return {"id": rec["id"]}

# ---------- Optional: call your RPCs (Postgres functions) ----------

async def rpc_ingest_phone_logs(max_rows: int = 100) -> int:
    """
    SELECT dev_nexus.usp_IngestPhoneCallLogs(p_max_rows := $1);
    Returns number of rows processed.
    """
    sql = "select dev_nexus.usp_ingestphonecalllogs($1)"
    pool = _pool_required()
    async with pool.acquire() as conn:
        rec = await conn.fetchval(sql, max_rows)
        return int(rec)
