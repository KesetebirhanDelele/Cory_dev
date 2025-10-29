# app/data/supabase_repo.py
from __future__ import annotations

import os
from typing import Optional, Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from temporalio import activity
import httpx
from supabase import create_client, Client  # supabase-py
import json
from datetime import datetime

# ===============================================================
#  Supabase Configuration and Lazy Initialization
# ===============================================================

def _cfg() -> tuple[str, str, str]:
    """Resolve Supabase configuration from environment."""
    url = os.getenv("SUPABASE_URL")
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_KEY")
    )
    schema = os.getenv("SUPABASE_SCHEMA", "dev_nexus")
    if not url or not key:
        raise RuntimeError("Supabase not configured: set SUPABASE_URL and SUPABASE_SERVICE_ROLE (or *_KEY)")
    return url.rstrip("/"), key, schema


_sb: Optional[Client] = None
_db = None  # postgrest client with schema header


def _headers(key: str) -> Dict[str, str]:
    """Default headers for Supabase REST calls."""
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def get_client() -> Client:
    """Lazily create and cache Supabase client."""
    global _sb, _db
    if _sb is None:
        url, key, schema = _cfg()
        _sb = create_client(url, key)
        global _SCHEMA
        _SCHEMA = schema
    return _sb


def get_db():
    """Return a PostgREST client scoped to the configured schema."""
    global _db
    if _db is None:
        _, _, schema = _cfg()
        _db = get_client().postgrest.schema(schema)
    return _db


# ===============================================================
#  Error Handling and Retry Helpers
# ===============================================================

class TransientError(Exception):
    """Raised for transient HTTP errors that should trigger retry."""


def _raise_if_transient(status: int, detail: str = ""):
    """Raise for transient Supabase or network errors."""
    if status in (429, 500, 502, 503, 504):
        raise TransientError(detail)


# ===============================================================
#  RPC Helpers
# ===============================================================

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
    status = getattr(res, "status_code", 200)
    _raise_if_transient(status, detail=str(getattr(res, "error", "")))
    return res.data


# ===============================================================
#  REST Helpers (Async)
# ===============================================================

async def insert(table: str, json_body: dict):
    """Insert row(s) into a table and return representation."""
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
    """Perform a PATCH request to Supabase and return the full HTTP response."""
    url, key, schema = _cfg()
    full_url = f"{url}/rest/v1/{table}?{query}"
    print(f"[SUPABASE_PATCH] {full_url} | body={json_body}")

    headers = {**_headers(key), "Accept-Profile": schema, "Prefer": "return=representation"}

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.patch(full_url, json=json_body, headers=headers)

    print(f"[SUPABASE_PATCH_RESPONSE] {r.status_code}: {r.text}")
    return r  # ✅ return the Response object, not r.json()


async def rpc_async(name: str, payload: dict | None = None):
    """Call Postgres RPC asynchronously via REST."""
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


# ===============================================================
#  Interaction Logging
# ===============================================================

@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=3),
    retry=retry_if_exception_type(TransientError),
)
@activity.defn
async def insert_interaction(
    enrollment_id: str,
    channel: str,
    direction: str,
    status: str,
    content: str,
    message_type: str,
) -> None:
    """Insert a communication log entry into Supabase interactions table."""
    try:
        url, key, _ = _cfg()
        json_body = {
            "enrollment_id": enrollment_id,
            "channel": channel,
            "direction": direction,
            "status": status,
            "content": content,
            "message_type": message_type,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{url}/rest/v1/interactions",
                headers={**_headers(key), "Prefer": "return=representation"},
                json=json_body,
            )
            _raise_if_transient(r.status_code, r.text)
            r.raise_for_status()
    except Exception as e:
        print(f"[insert_interaction] Failed to log interaction: {e}")


# ===============================================================
#  Temporal Activity Wrappers
# ===============================================================
@activity.defn
async def patch_activity(table: str, query: str, json_body: dict):
    """Activity wrapper around the patch helper for Temporal workflows with improved validation/logging."""
    try:
        # --- Normalize datetime values for Supabase ---
        for key, value in json_body.items():
            if isinstance(value, datetime):
                json_body[key] = value.strftime("%Y-%m-%d %H:%M:%S")
            elif isinstance(value, str) and "T" in value:
                json_body[key] = value.replace("T", " ").replace("Z", "")

        print(f"[PATCH_ACTIVITY] PATCH {table}?{query} => {json.dumps(json_body)}")

        # --- Execute PATCH ---
        r = await patch(table, query, json_body)  # returns httpx.Response

        if r.status_code >= 400:
            print(f"[PATCH_ACTIVITY_ERROR] HTTP {r.status_code}: {r.text}")
            r.raise_for_status()

        print(f"[PATCH_ACTIVITY_SUCCESS] Updated {table} where {query}")

        # ✅ Return JSON-serializable result (Temporal-safe)
        return {
            "status": r.status_code,
            "data": r.json()
        }

    except Exception as e:
        print(f"[PATCH_ACTIVITY_EXCEPTION] {type(e).__name__}: {e}")
        raise



