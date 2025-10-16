# app/data/supabase_repo.py
from __future__ import annotations

import os
from typing import Optional, Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

import httpx
from supabase import create_client, Client  # supabase-py

# ---- Config / singletons (lazy to avoid import-time KeyError) ----

def _cfg() -> tuple[str, str, str]:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    schema = os.getenv("SUPABASE_SCHEMA", "dev_nexus")
    if not url or not key:
        raise RuntimeError("Supabase not configured: set SUPABASE_URL and SUPABASE_SERVICE_ROLE (or *_KEY)")
    return url.rstrip("/"), key, schema

_sb: Optional[Client] = None
_db = None  # postgrest client with schema header

def _headers(key: str) -> Dict[str, str]:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

def get_client() -> Client:
    """Lazily create and cache supabase client."""
    global _sb, _db
    if _sb is None:
        url, key, schema = _cfg()
        _sb = create_client(url, key)
        # Attach a schema-scoped postgrest client for RPC/table ops
        # Note: RPC calls honor Accept-Profile (schema) in PostgREST.
        global _SCHEMA
        _SCHEMA = schema
    return _sb

def get_db():
    """Return a PostgREST client scoped to our schema."""
    global _db
    if _db is None:
        _, _, schema = _cfg()
        _db = get_client().postgrest.schema(schema)
    return _db

# ---- Errors & retry policy ----

class TransientError(Exception):
    """Raise for 429/5xx to trigger retry."""

def _raise_if_transient(status: int, detail: str = ""):
    if status in (429, 500, 502, 503, 504):
        raise TransientError(detail)

# ---- RPC (sync via supabase-py) ----

@retry(
    reraise=True,
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=0.2, min=0.2, max=5),
    retry=retry_if_exception_type(TransientError),
)
def rpc(name: str, payload: dict | None = None):
    """Call Postgres function via PostgREST RPC using schema profile."""
    db = get_db()
    res = db.rpc(name, payload or {}).execute()
    # supabase-py returns a response object with status_code & data
    status = getattr(res, "status_code", 200)
    _raise_if_transient(status, detail=str(getattr(res, "error", "")))
    return res.data

# ---- REST helpers (async via httpx) ----

async def insert(table: str, json_body: dict):
    """Insert row(s) and return representation (Prefer=representation)."""
    url, key, _ = _cfg()
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"{url}/rest/v1/{table}",
            headers={**_headers(key), "Prefer": "return=representation"},
            json=json_body,
        )
        _raise_if_transient(r.status_code, r.text)
        r.raise_for_status()
        return r.json()

async def patch(table: str, query: str, json_body: dict):
    """Generic PATCH helper: query is e.g. 'id=eq.123'."""
    url, key, _ = _cfg()
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.patch(
            f"{url}/rest/v1/{table}?{query}",
            headers={**_headers(key), "Prefer": "return=representation"},
            json=json_body,
        )
        _raise_if_transient(r.status_code, r.text)
        r.raise_for_status()
        return r.json()

async def rpc_async(name: str, payload: dict | None = None):
    """RPC via REST (async), useful inside async workers."""
    url, key, schema = _cfg()
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"{url}/rest/v1/rpc/{name}",
            headers={**_headers(key), "Accept-Profile": schema},
            json=payload or {},
        )
        _raise_if_transient(r.status_code, r.text)
        r.raise_for_status()
        return r.json()
