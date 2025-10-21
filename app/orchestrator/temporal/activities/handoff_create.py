# app/orchestrator/temporal/activities/handoff_create.py
from __future__ import annotations

import os
import uuid
from typing import Any, Dict

import httpx
from temporalio import activity

# ---- Config & helpers ---------------------------------------------------------
def _require_env(name: str) -> str:
    v = (os.getenv(name) or "").strip()
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v

SUPABASE_URL = _require_env("SUPABASE_URL").rstrip("/")
SUPABASE_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE")
    or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("SUPABASE_KEY")
    or ""
).strip()
if not SUPABASE_KEY:
    raise RuntimeError("Set SUPABASE_SERVICE_ROLE (or *_KEY) for server-side REST access")

# Allow overriding the timeout status to match your enum labels (e.g., 'expired')
TIMEOUT_STATUS = (os.getenv("HANDOFF_TIMEOUT_STATUS") or "expired").strip()

def _headers() -> Dict[str, str]:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

def _org_id_from(body: Dict[str, Any]) -> str:
    org_id = (body.get("organization_id") or os.getenv("TEST_ORG_ID") or "").strip()
    if not org_id:
        raise RuntimeError("organization_id is required (provide in workflow input or set TEST_ORG_ID)")
    return org_id

def _db_payload_from_workflow(body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "organization_id": _org_id_from(body),
        "title": body["subject"],
        "task_type": "manual_review",       # adjust if your schema expects specific values
        "source": "temporal",
        "source_key": body.get("workflow_run_id"),
        "lead_id": None,
        "interaction_id": None,
        "description": f"Channel={body.get('channel')}",
        "priority": "normal",
        "assigned_to": body.get("assignee"),
        "metadata": {
            "channel": body.get("channel"),
            "payload": body.get("payload") or {},
            "created_by": body.get("created_by"),
            "timeout_seconds": body.get("timeout_seconds"),
        },
    }

# ---- Activities ---------------------------------------------------------------

@activity.defn(name="create_handoff")
async def create_handoff(body: Dict[str, Any]) -> str:
    """Insert a handoff row and return its id."""
    if os.getenv("HANDOFF_FAKE_MODE") == "1":
        return str(uuid.uuid4())

    db_body = _db_payload_from_workflow(body)
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"{SUPABASE_URL}/rest/v1/handoffs",
            headers={**_headers(), "Prefer": "return=representation"},
            json=db_body,
        )
        if r.status_code >= 400:
            # Bubble up PostgREST error body for fast debugging
            raise RuntimeError(f"handoffs insert failed {r.status_code}: {r.text}")
        data = r.json()
        return data[0]["id"] if isinstance(data, list) else data["id"]

@activity.defn(name="resolve_handoff_rpc")
async def resolve_handoff_rpc(body: Dict[str, Any]) -> Dict[str, Any]:
    """Call the resolve RPC with a resolution payload."""
    if os.getenv("HANDOFF_FAKE_MODE") == "1":
        return {
            "ok": True,
            "handoff_id": body["handoff_id"],
            "resolution": body.get("resolution_payload", {}),
        }

    payload = {
        "p_handoff": body["handoff_id"],
        "p_resolution": body.get("resolution_payload") or {},
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"{SUPABASE_URL}/rest/v1/rpc/resolve_handoff",
            headers=_headers(),
            json=payload,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"resolve_handoff RPC failed {r.status_code}: {r.text}")
        return r.json()

@activity.defn(name="mark_timed_out")
async def mark_timed_out(body: Dict[str, Any]) -> None:
    """Set status to the configured timeout/expiry label (enum-safe)."""
    if os.getenv("HANDOFF_FAKE_MODE") == "1":
        return None

    handoff_id = body["handoff_id"]
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.patch(
            f"{SUPABASE_URL}/rest/v1/handoffs?id=eq.{handoff_id}",
            headers={**_headers(), "Prefer": "return=minimal"},
            json={"status": TIMEOUT_STATUS},   # default 'expired'; override via HANDOFF_TIMEOUT_STATUS
        )
        if r.status_code >= 400:
            raise RuntimeError(f"handoffs patch failed {r.status_code}: {r.text}")

__all__ = ["create_handoff", "resolve_handoff_rpc", "mark_timed_out"]
