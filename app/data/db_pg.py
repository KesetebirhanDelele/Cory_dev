# app/data/db_pg.py

import os
import asyncpg
from typing import Any, Dict, List, Optional
from supabase import create_client


# ---------------------------------------------------------------------
#  SUPABASE CLIENT (HTTP API)
# ---------------------------------------------------------------------

SUPABASE_URL = os.getenv("SUPABASE_URL")

# Prefer SUPABASE_SERVICE_KEY, but fall back to SUPABASE_SERVICE_ROLE_KEY
SUPABASE_SERVICE_KEY = (
    os.getenv("SUPABASE_SERVICE_KEY")
    or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
)

if not SUPABASE_URL:
    raise RuntimeError(
        "Missing SUPABASE_URL in environment (.env). "
        "Get it from Supabase → Settings → API."
    )

if not SUPABASE_SERVICE_KEY:
    raise RuntimeError(
        "Missing SUPABASE_SERVICE_KEY / SUPABASE_SERVICE_ROLE_KEY in environment (.env). "
        "Use the *service_role* key from Supabase (NOT the anon key)."
    )

# Create supabase client
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# ---------------------------------------------------------------------
#  POSTGRES CONNECTION (asyncpg)
# ---------------------------------------------------------------------

# DATABASE_URL should point to the Supabase Postgres DSN
_DSN: Optional[str] = os.getenv("DATABASE_URL")

_pool: Optional[asyncpg.Pool] = None


async def init_db_pool() -> asyncpg.Pool:
    """
    Initialize the asyncpg pool once.
    Called at startup by email_ingest_daemon + workflows.
    """
    global _pool

    if _pool is None:
        if not _DSN:
            raise RuntimeError(
                "DATABASE_URL is not set in .env. "
                "Use the Supabase Postgres DSN from Settings → Database."
            )

        _pool = await asyncpg.create_pool(
            dsn=_DSN,
            min_size=1,
            max_size=5,
        )

    return _pool


def get_pool() -> asyncpg.Pool:
    """
    Returns the active pool.
    """
    if _pool is None:
        raise RuntimeError(
            "DB pool not initialized — call init_db_pool() first."
        )
    return _pool


# ---------------------------------------------------------------------
#  QUERY HELPERS
# ---------------------------------------------------------------------

async def fetchrow(sql: str, *args: Any) -> Optional[Dict[str, Any]]:
    """
    Fetch exactly one row or None.
    """
    pool = _pool or await init_db_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *args)
        return dict(row) if row is not None else None


async def fetch(sql: str, *args: Any) -> List[Dict[str, Any]]:
    """
    Fetch multiple rows, returned as list of dicts.
    """
    pool = _pool or await init_db_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
        return [dict(r) for r in rows]


async def execute(sql: str, *args: Any) -> str:
    """
    Execute INSERT / UPDATE / DELETE.
    Returns asyncpg's status string.
    """
    pool = _pool or await init_db_pool()

    async with pool.acquire() as conn:
        return await conn.execute(sql, *args)


# ---------------------------------------------------------------------
#  LEGACY COMPAT WRAPPER
# ---------------------------------------------------------------------

async def run_query(sql: str, *args: Any) -> List[Dict[str, Any]]:
    """
    Legacy helper (same as fetch()).
    """
    return await fetch(sql, *args)
