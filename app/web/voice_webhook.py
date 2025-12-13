# app/web/voice_webhook.py

import datetime
import json
import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, Request
from postgrest.exceptions import APIError
from supabase import create_client

from temporalio.client import Client
from app.orchestrator.temporal.workflows.missed_call_followup import (
    MissedCallFollowupWorkflow,
)

router = APIRouter()
log = logging.getLogger("cory.voice.webhook")

# ---------------------------------------------------------------------
# Supabase client
# ---------------------------------------------------------------------
supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
)

DEFAULT_PROJECT_ID = os.getenv("DEFAULT_PROJECT_ID")

# ---------------------------------------------------------------------
# Temporal client (lazy singleton)
# ---------------------------------------------------------------------
TEMPORAL_TARGET = (
    os.getenv("TEMPORAL_ADDRESS")  # typical Temporal address env
    or os.getenv("TEMPORAL_HOST")  # fallback if you used this name
    or "localhost:7233"
)
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
TEMPORAL_TASK_QUEUE = os.getenv("TEMPORAL_COMM_TASK_QUEUE", "comm-q")

_temporal_client: Client | None = None


async def get_temporal_client() -> Client:
    global _temporal_client
    if _temporal_client is None:
        log.info(
            "[Temporal] Connecting to Temporal at %s (namespace=%s)",
            TEMPORAL_TARGET,
            TEMPORAL_NAMESPACE,
        )
        _temporal_client = await Client.connect(
            TEMPORAL_TARGET,
            namespace=TEMPORAL_NAMESPACE,
        )
    return _temporal_client


# Status values that we treat as "missed call / voicemail"
MISSED_CALL_STATUSES = {
    "no_answer",
    "busy",
    "failed",
    "voicemail",
    "not_answered",
    "missed",
}


def _extract_custom_variables(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Synthflow echoes our custom_variables somewhere in the webhook payload.
    We try a couple of common locations and normalize into a simple dict.

    Expected shapes e.g.:

        "custom_variables": [
            {"key": "enrollment_id", "value": "..." },
            {"key": "reason_for_call", "value": "..." }
        ]
    """
    custom_vars: Dict[str, Any] = {}

    candidates = []

    # Root-level array: data["custom_variables"] = [{ "key": ..., "value": ... }, ...]
    if isinstance(data.get("custom_variables"), list):
        candidates.append(data["custom_variables"])

    # Nested under metadata: data["metadata"]["custom_variables"]
    metadata = data.get("metadata") or {}
    if isinstance(metadata.get("custom_variables"), list):
        candidates.append(metadata["custom_variables"])

    for arr in candidates:
        for item in arr:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            value = item.get("value")
            if key:
                custom_vars[key] = value

    # Also allow simple metadata-flattened vars (e.g. metadata["enrollment_id"])
    for k in ("enrollment_id", "org_id", "reason_for_call", "campaign_id"):
        if k not in custom_vars and k in metadata:
            custom_vars[k] = metadata[k]

    return custom_vars


@router.post("/api/voice/transcript")
async def receive_transcript(request: Request):
    """
    Webhook endpoint that receives a transcript payload from Synthflow,
    logs it into the `message` table, and on missed calls starts the
    MissedCallFollowupWorkflow (30s SMS #1 → 25s SMS #2 → nurture).

    Expected shape (simplified):

    {
      "status": "completed",
      "lead": {
        "name": "Evelyn Brooks",
        "phone_number": "+15714782790"
      },
      "call": {
        "call_id": "82ef7b81-...",
        "status": "completed",
        "result": "voicemail" | "no_answer" | "completed",
        "transcript": "...",
        "recording_url": "https://..."
      },
      "analysis": { ... },
      "metadata": {
        "custom_variables": [
          {"key": "enrollment_id", "value": "bbbb-..."},
          {"key": "reason_for_call", "value": "your application to ..."},
          {"key": "campaign_id", "value": "aaaa-..."}
        ]
      }
    }
    """
    data = await request.json()
    log.info("[Webhook] Received payload from Synthflow: %s", json.dumps(data)[:500])

    # ✅ Unwrap Synthflow JSON structure
    call = data.get("call", {}) or {}
    provider_ref = call.get("call_id") or data.get("call_id")

    # Transcript & audio URL (top-level columns in the message table)
    transcript = call.get("transcript") or data.get("transcript") or ""
    audio_url = (
        call.get("recording_url")
        or data.get("recording_url")
        or data.get("audio_url")
    )

    # Optional metadata: used for logging/diagnostics
    lead = data.get("lead", {}) or {}
    lead_name = lead.get("name")
    lead_phone = lead.get("phone_number")

    # Pull our custom variables back out (enrollment_id, reason_for_call, etc.)
    custom_vars = _extract_custom_variables(data)
    enrollment_id = custom_vars.get("enrollment_id")
    campaign_id = custom_vars.get("campaign_id")
    reason_for_call = custom_vars.get("reason_for_call")

    project_id = DEFAULT_PROJECT_ID

    if not provider_ref:
        log.warning("[Webhook] Missing call_id in Synthflow payload: %s", list(data.keys()))
        return {"error": "Missing call_id"}, 400

    # Normalize status so it lines up with VoiceConversationAgent._collect_transcript,
    # which currently checks for "complete".
    raw_status = call.get("status") or data.get("status", "completed")
    normalized_status = "complete" if raw_status == "completed" else str(raw_status)

    # Try to infer a more detailed call result (for missed-call detection)
    call_result = (
        call.get("result")
        or call.get("disposition")
        or data.get("result")
        or data.get("disposition")
        or normalized_status
    )
    call_result = (call_result or "").lower()
    is_missed_call = call_result in MISSED_CALL_STATUSES

    # Store rich content, including a flag for missed-call detection
    content = {
        "transcript": transcript,
        "audio_url": audio_url,
        "raw_payload": data,
        "call_result": call_result,
        "is_missed_call": is_missed_call,
        "campaign_id": campaign_id,
        "reason_for_call": reason_for_call,
    }

    now = datetime.datetime.now(datetime.UTC).isoformat()
    record = {
        "project_id": project_id,
        "enrollment_id": enrollment_id,
        "channel": "voice",
        "direction": "inbound",
        "provider_ref": provider_ref,
        # Prefer call.status if present, else top-level status, normalized
        "status": normalized_status,
        # content is stored as JSONB in the `message` table
        "content": content,
        "transcript": transcript,
        "audio_url": audio_url,
        "occurred_at": now,
        "created_at": now,
    }

    try:
        supabase.table("message").insert(record).execute()
        log.info(
            "✅ Stored voice transcript for call_id=%s (phone=%s, lead=%s, status=%s, result=%s, missed=%s)",
            provider_ref,
            lead_phone,
            lead_name,
            normalized_status,
            call_result,
            is_missed_call,
        )

        # On missed call → start Temporal workflow to handle SMS reminders + nurture
        if is_missed_call and lead_phone:
            log.info(
                "[MissedCall] Detected missed call for %s "
                "(enrollment_id=%s, campaign_id=%s, reason=%s); "
                "starting MissedCallFollowupWorkflow.",
                lead_phone,
                enrollment_id,
                campaign_id,
                reason_for_call,
            )
            try:
                client = await get_temporal_client()
                workflow_id = f"missed-call-{provider_ref}"
                await client.start_workflow(
                    MissedCallFollowupWorkflow.run,
                    # workflow arguments:
                    lead_phone,
                    enrollment_id,
                    campaign_id,
                    os.getenv("NURTURE_CAMPAIGN_ID"),
                    id=workflow_id,
                    task_queue=TEMPORAL_TASK_QUEUE,
                )
                log.info(
                    "[MissedCall] Started MissedCallFollowupWorkflow | workflow_id=%s",
                    workflow_id,
                )
            except Exception as wf_ex:  # noqa: BLE001
                # Do NOT fail the webhook for provider; just log the error
                log.exception(
                    "[MissedCall] Failed to start MissedCallFollowupWorkflow: %s",
                    wf_ex,
                )

        return {"success": True, "provider_ref": provider_ref}

    except APIError as e:
        if "duplicate key value violates unique constraint" in str(e):
            log.warning("[Webhook] Duplicate provider_ref=%s ignored.", provider_ref)
            return {"success": True, "duplicate": True, "provider_ref": provider_ref}
        log.exception("[Webhook] Supabase API error while inserting transcript")
        return {"error": str(e)}, 500

    except Exception as ex:  # noqa: BLE001
        log.exception("[Webhook] Unexpected error while inserting transcript")
        return {"error": str(ex)}, 500
