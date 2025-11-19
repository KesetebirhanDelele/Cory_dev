# app/data/supabase_repo.py
from __future__ import annotations

import os
import json
from datetime import datetime
from typing import Optional, Dict, Any

import httpx
from supabase import create_client, Client
from temporalio import activity
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

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
        raise RuntimeError(
            "Supabase not configured: set SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE (or *_KEY)"
        )
    return url.rstrip("/"), key, schema


_sb: Optional[Client] = None
_db = None
_SCHEMA: Optional[str] = None


def _headers(key: str) -> Dict[str, str]:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def get_client() -> Client:
    global _sb, _SCHEMA
    if _sb is None:
        url, key, schema = _cfg()
        _sb = create_client(url, key)
        _SCHEMA = schema
    return _sb


def get_db():
    global _db
    if _db is None:
        _, _, schema = _cfg()
        _db = get_client().postgrest.schema(schema)
    return _db

# ===============================================================
#  Retry Utilities
# ===============================================================

class TransientError(Exception):
    pass


def _raise_if_transient(status: int, detail: str = ""):
    if status in (429, 500, 502, 503, 504):
        raise TransientError(detail)

# ===============================================================
#  REST Helpers
# ===============================================================

async def insert(table: str, json_body: dict):
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
    url, key, schema = _cfg()
    full_url = f"{url}/rest/v1/{table}?{query}"
    headers = {
        **_headers(key),
        "Accept-Profile": schema,
        "Prefer": "return=representation",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.patch(full_url, json=json_body, headers=headers)
    _raise_if_transient(r.status_code, r.text)
    return r

# ===============================================================
#  Voice Conversation / Synthflow Support
# ===============================================================

class SupabaseRepo:
    """Repository for Supabase operations used by agents and callbacks."""

    def __init__(self) -> None:
        self.url, self.key, self.schema = _cfg()
        self.client: Client = get_client()

    # -------- Voice transcript handling ---------------------------------------

    async def upsert_call_event(self, event: dict):
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
        r = await patch("lead_campaign_steps", query, body)
        return r

    async def get_message_by_provider_ref(self, provider_ref: str) -> dict:
        url, key, schema = _cfg()
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{url}/rest/v1/message"
                f"?provider_ref=eq.{provider_ref}"
                "&select=content,transcript,status",
                headers={**_headers(key), "Accept-Profile": schema},
            )
        if r.status_code == 200 and r.json():
            return r.json()[0]
        return {}

    async def update_lead_campaign_step(self, step_id: str, fields: dict):
        body = {**fields, "updated_at": datetime.utcnow().isoformat()}
        query = f"id=eq.{step_id}"
        return await patch("lead_campaign_steps", query, body)

    # ===============================================================
    #  Appointment / Handoff  (Ticket 5 updates)
    # ===============================================================

    async def create_appointment_task(self, lead_id: str, context: dict | None = None):
        """
        Ticket 5 update:
        - Accepts context
        - Saves context into handoff_tasks.context
        """
        payload: Dict[str, Any] = {
            "lead_id": lead_id,
            "type": "appointment_request",
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
        }

        if context:
            payload["context"] = context

        return await insert("handoff_tasks", payload)

    async def create_appointment(
        self,
        *,
        lead_id: str,
        enrollment_id: str | None = None,
        campaign_id: str | None = None,
        scheduled_for: datetime,
        channel: str = "voice",
        source: str = "cory",
        calendar_event_id: str | None = None,
        notes: str | None = None,
    ) -> dict:

        payload: Dict[str, Any] = {
            "lead_id": lead_id,
            "enrollment_id": enrollment_id,
            "campaign_id": campaign_id,
            "channel": channel,
            "source": source,
            "scheduled_for": scheduled_for.isoformat(),
            "status": "scheduled",
            "calendar_event_id": calendar_event_id,
            "notes": notes,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }

        payload = {k: v for k, v in payload.items() if v is not None}

        rows = await insert("appointments", payload)
        return rows[0] if isinstance(rows, list) and rows else rows

    async def update_appointment_status(
        self,
        appointment_id: str,
        status: str,
        *,
        calendar_event_id: str | None = None,
        notes: str | None = None,
    ):
        fields: Dict[str, Any] = {
            "status": status,
            "updated_at": datetime.utcnow().isoformat(),
        }

        if calendar_event_id is not None:
            fields["calendar_event_id"] = calendar_event_id
        if notes is not None:
            fields["notes"] = notes

        query = f"id=eq.{appointment_id}"
        return await patch("appointments", query, fields)

# ===============================================================
#  RPC Utilities
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
#  Temporal-safe Patch Wrapper
# ===============================================================

@activity.defn
async def patch_activity(table: str, query: str, json_body: dict):
    try:
        for k, v in json_body.items():
            if isinstance(v, datetime):
                json_body[k] = v.strftime("%Y-%m-%d %H:%M:%S")
            elif isinstance(v, str) and "T" in v:
                json_body[k] = v.replace("T", " ").replace("Z", "")

        r = await patch(table, query, json_body)

        if r.status_code >= 400:
            r.raise_for_status()

        return {"status": r.status_code, "data": r.json()}
    except Exception as e:
        raise
