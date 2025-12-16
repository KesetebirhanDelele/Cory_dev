# app/orchestrator/temporal/activities/handoff_create.py
# ---------------------------------------------------------------------------
# ✅ Temporal Activity: Handoff Creation, Resolution, and Timeout Handling
# ---------------------------------------------------------------------------
from __future__ import annotations

import os
import uuid
from typing import Any, Dict
import httpx
from temporalio import activity

# ---------------------------------------------------------------------------
# ✅ 1. Load environment early and reliably
# ---------------------------------------------------------------------------
from dotenv import load_dotenv, find_dotenv

dotenv_path = find_dotenv(usecwd=True)
if dotenv_path:
    load_dotenv(dotenv_path, override=True)
    print(f"[BOOTSTRAP] Loaded .env from {dotenv_path}")
else:
    print("[BOOTSTRAP] ⚠️ No .env file found when loading handoff_create.py")

# ---------------------------------------------------------------------------
# ✅ 2. Helpers for configuration
# ---------------------------------------------------------------------------


def _require_env(name: str) -> str:
    """Require an environment variable, fallback to .env if missing."""
    val = (os.getenv(name) or "").strip()
    if not val:
        # Try again after attempting to load dotenv dynamically
        load_dotenv(find_dotenv(usecwd=True), override=True)
        val = (os.getenv(name) or "").strip()
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


SUPABASE_URL = _require_env("SUPABASE_URL").rstrip("/")
SUPABASE_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE")
    or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("SUPABASE_KEY")
    or ""
).strip()

if not SUPABASE_KEY:
    raise RuntimeError("Set SUPABASE_SERVICE_ROLE (or *_KEY) for server-side REST access")

TIMEOUT_STATUS = (os.getenv("HANDOFF_TIMEOUT_STATUS") or "expired").strip()


def _headers() -> Dict[str, str]:
    """Standard Supabase REST headers."""
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def _org_id_from(body: Dict[str, Any]) -> str:
    """Extract organization_id or use TEST_ORG_ID fallback."""
    org_id = (body.get("organization_id") or os.getenv("TEST_ORG_ID") or "").strip()
    if not org_id:
        raise RuntimeError(
            "organization_id is required (provide in workflow input or set TEST_ORG_ID)"
        )
    return org_id


def _db_payload_from_workflow(body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Shape the handoff record according to DB schema.

    This is the bridge between Temporal workflows (RAG / SMS / voice)
    and the Supabase `handoffs` table.

    Expected body keys (not all required):

        {
          "organization_id": "3333-...",
          "workflow_run_id": "<Temporal workflow id>",
          "channel": "sms" | "voice" | "email",
          "subject": "Student ready to enroll",
          "priority": "normal" | "high",
          "assignee": "advisor@school.edu",

          # Lead / contact / enrollment context
          "lead_id": "<contact_id or lead_id in DB>",
          "interaction_id": "<message.id or call.id>",
          "enrollment_id": "<enrollment uuid>",

          # Conversation / intent context
          "intent": "ready_to_enroll" | "needs_human" | ...,
          "next_action": "handoff_to_human" | ...,
          "last_message": {
              "text": "... full student message ...",
              "channel": "sms",
              "from": "+1...",
          },

          # Optional booking context (ticket 7)
          "booking": {
              "booking_link": "https://calendly.com/...",
              "status": "link_sent" | "confirmed",
              "appointment_time": "2025-09-01T15:00:00Z",
          },

          # Free-form payload (anything else you want to log)
          "payload": { ... },

          # Metadata
          "created_by": "cory-system",
          "timeout_seconds": 3600
        }

    Anything in `payload` is stored inside metadata.payload.
    """
    last_message = body.get("last_message") or {}
    booking = body.get("booking") or {}

    metadata: Dict[str, Any] = {
        "channel": body.get("channel"),
        "payload": body.get("payload") or {},
        "created_by": body.get("created_by"),
        "timeout_seconds": body.get("timeout_seconds"),
        # Intent / routing context from RAG
        "intent": body.get("intent"),
        "next_action": body.get("next_action"),
        # Conversation snapshot for the human
        "last_message": last_message,
        # Enrollment context (helps advisors see where in the flow this is)
        "enrollment_id": body.get("enrollment_id"),
        # Booking info (link or confirmed appointment)
        "booking": booking,
    }

    # Clean out None values to avoid noisy JSON
    metadata = {k: v for k, v in metadata.items() if v is not None}

    return {
        "organization_id": _org_id_from(body),
        "title": body.get("subject", "Manual Review"),
        "task_type": "manual_review",
        "source": "temporal",
        "source_key": body.get("workflow_run_id"),
        "lead_id": body.get("lead_id"),
        "interaction_id": body.get("interaction_id"),
        "description": f"Channel={body.get('channel')}",
        "priority": body.get("priority", "normal"),
        "assigned_to": body.get("assignee"),
        "metadata": metadata,
    }


# ---------------------------------------------------------------------------
# ✅ 3. Activities
# ---------------------------------------------------------------------------


@activity.defn(name="create_handoff")
async def create_handoff(body: Dict[str, Any]) -> str:
    """
    Insert a new handoff row into Supabase and return its id.

    Typical usage from a workflow when intent is "ready_to_enroll" or "needs_human":

        handoff_id = await workflow.execute_activity(
            create_handoff,
            {
                "organization_id": org_id,
                "workflow_run_id": workflow.info().workflow_id,
                "channel": "sms",
                "subject": "Student ready to talk to advisor",
                "priority": "high",
                "lead_id": contact_id,
                "enrollment_id": enrollment_id,
                "interaction_id": message_id,
                "intent": intent,
                "next_action": next_action,
                "last_message": {
                    "text": "<student sms>",
                    "channel": "sms",
                    "from": from_number,
                },
                "booking": {
                    "booking_link": "<optional link>",
                    "status": "link_sent",
                },
                "payload": {...},
            },
            start_to_close_timeout=timedelta(seconds=30),
        )
    """
    if os.getenv("HANDOFF_FAKE_MODE") == "1":
        return str(uuid.uuid4())

    db_body = _db_payload_from_workflow(body)
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/handoffs",
            headers={**_headers(), "Prefer": "return=representation"},
            json=db_body,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"handoffs insert failed {resp.status_code}: {resp.text}")
        data = resp.json()
        return data[0]["id"] if isinstance(data, list) else data.get("id")


@activity.defn(name="resolve_handoff_rpc")
async def resolve_handoff_rpc(body: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve a handoff by invoking the Supabase RPC."""
    if os.getenv("HANDOFF_FAKE_MODE") == "1":
        return {
            "ok": True,
            "handoff_id": body.get("handoff_id"),
            "resolution": body.get("resolution_payload", {}),
        }

    payload = {
        "p_handoff": body.get("handoff_id"),
        "p_resolution": body.get("resolution_payload") or {},
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/rpc/resolve_handoff",
            headers=_headers(),
            json=payload,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"resolve_handoff RPC failed {resp.status_code}: {resp.text}")
        return resp.json()


@activity.defn(name="mark_timed_out")
async def mark_timed_out(body: Dict[str, Any]) -> None:
    """Mark a handoff as expired after timeout."""
    if os.getenv("HANDOFF_FAKE_MODE") == "1":
        return None

    handoff_id = body.get("handoff_id")
    if not handoff_id:
        raise RuntimeError("handoff_id missing in mark_timed_out input")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.patch(
            f"{SUPABASE_URL}/rest/v1/handoffs?id=eq.{handoff_id}",
            headers={**_headers(), "Prefer": "return=minimal"},
            json={"status": TIMEOUT_STATUS},
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"handoffs patch failed {resp.status_code}: {resp.text}")


__all__ = ["create_handoff", "resolve_handoff_rpc", "mark_timed_out"]
