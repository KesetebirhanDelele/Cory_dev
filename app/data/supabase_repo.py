# app/data/supabase_repo.py
from __future__ import annotations
import os, json, httpx
from typing import Optional, Dict, Any
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from temporalio import activity
from supabase import create_client, Client


# ===============================================================
#  Configuration Helpers
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
_db = None  # PostgREST client with schema header


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
#  Retry Utilities
# ===============================================================

class TransientError(Exception):
    """Raised for transient HTTP/network errors that should trigger retry."""


def _raise_if_transient(status: int, detail: str = ""):
    if status in (429, 500, 502, 503, 504):
        raise TransientError(detail)


# ===============================================================
#  REST Helpers
# ===============================================================

async def insert(table: str, json_body: dict):
    """Insert record(s) into a Supabase table."""
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
    """Perform PATCH on Supabase table."""
    url, key, schema = _cfg()
    full_url = f"{url}/rest/v1/{table}?{query}"
    headers = {**_headers(key), "Accept-Profile": schema, "Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.patch(full_url, json=json_body, headers=headers)
    _raise_if_transient(r.status_code, r.text)
    return r


# ===============================================================
#  Voice Conversation / Synthflow Support
# ===============================================================

class SupabaseRepo:
    """Repository for Supabase operations used by agents and callbacks."""

    def __init__(self):
        self.url, self.key, self.schema = _cfg()
        self.client = get_client()

    # --- Voice / Transcript Methods ---------------------------------------

    async def upsert_call_event(self, event: dict):
        """
        Persist Synthflow call transcript and metadata into lead_campaign_steps.
        Expected keys: call_id, transcript, raw_payload.
        """
        call_id = event.get("call_id")
        if not call_id:
            raise ValueError("Missing call_id for upsert_call_event")

        transcript = event.get("transcript") or ""
        raw_payload = event.get("raw_payload") or {}
        updated_at = event.get("updated_at") or datetime.utcnow().isoformat()

        body = {
            "transcript": transcript,
            "metadata": raw_payload,
            "updated_at": updated_at,
        }

        query = f"provider_ref=eq.{call_id}"
        print(f"[SupabaseRepo] Updating lead_campaign_steps where {query}")
        r = await patch("lead_campaign_steps", query, body)
        print(f"[SupabaseRepo] upsert_call_event response: {r.status_code}")
        return r

    async def get_call_transcript(self, call_id: str) -> str:
        """Fetch transcript text for a given Synthflow call."""
        url, key, schema = _cfg()
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{url}/rest/v1/lead_campaign_steps?provider_ref=eq.{call_id}&select=transcript",
                headers={**_headers(key), "Accept-Profile": schema},
            )
        if r.status_code == 200 and r.json():
            return r.json()[0].get("transcript", "")
        return ""

    async def update_lead_campaign_step(self, step_id: str, fields: dict):
        """Patch lead_campaign_steps by id (step_id)."""
        body = {**fields, "updated_at": datetime.utcnow().isoformat()}
        query = f"id=eq.{step_id}"
        return await patch("lead_campaign_steps", query, body)

    async def create_appointment_task(self, lead_id: str):
        """Create a handoff/appointment task for ready-to-enroll leads."""
        payload = {
            "lead_id": lead_id,
            "type": "appointment_request",
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
        }
        return await insert("handoff_tasks", payload)


# ===============================================================
#  Generic Logging & RPCs
# ===============================================================

@retry(
    reraise=True,
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=0.3, min=0.2, max=5),
    retry=retry_if_exception_type(TransientError),
)
def rpc(name: str, payload: dict | None = None):
    db = get_db()
    res = db.rpc(name, payload or {}).execute()
    _raise_if_transient(getattr(res, "status_code", 200))
    return res.data


async def rpc_async(name: str, payload: dict | None = None):
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
#  Temporal Activity Wrappers
# ===============================================================

@activity.defn
async def patch_activity(table: str, query: str, json_body: dict):
    """Temporal-safe wrapper for Supabase patch."""
    try:
        # Normalize datetimes for Supabase
        for k, v in json_body.items():
            if isinstance(v, datetime):
                json_body[k] = v.strftime("%Y-%m-%d %H:%M:%S")
            elif isinstance(v, str) and "T" in v:
                json_body[k] = v.replace("T", " ").replace("Z", "")

        print(f"[PATCH_ACTIVITY] {table}?{query} => {json.dumps(json_body)}")
        r = await patch(table, query, json_body)
        if r.status_code >= 400:
            print(f"[PATCH_ACTIVITY_ERROR] {r.status_code}: {r.text}")
            r.raise_for_status()

        return {"status": r.status_code, "data": r.json()}
    except Exception as e:
        print(f"[PATCH_ACTIVITY_EXCEPTION] {type(e).__name__}: {e}")
        raise
