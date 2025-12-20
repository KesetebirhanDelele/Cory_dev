# app/web/voice_webhook.py

import datetime
import json
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from postgrest.exceptions import APIError
from supabase import create_client
from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

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
    or os.getenv("TEMPORAL_TARGET")  # explicit override
    or "localhost:7233"
)
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")

# 🔥 IMPORTANT: default queue matches worker CAMPAIGN_QUEUE
TEMPORAL_TASK_QUEUE = os.getenv(
    "TEMPORAL_COMM_TASK_QUEUE",
    "cory-handoff-queue",
)
print("TEMPORAL_TASK_QUEUE from env =", TEMPORAL_TASK_QUEUE)

_temporal_client: Optional[Client] = None


async def get_temporal_client() -> Client:
    """Singleton Temporal client so we don't reconnect on every webhook."""
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
        log.info("[Temporal] Connected.")
    return _temporal_client


# Status values that we treat as "missed call / voicemail"
MISSED_CALL_STATUSES = {
    "no_answer",
    "not_answered",
    "busy",
    "failed",
    "voicemail",
    "hangup_on_voicemail",
    "missed",
}


def _extract_custom_variables(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Try to pull any custom_variables / prompt_variables from known Synthflow shapes.

    This is *best-effort only*:
      - If nothing is present, we just return an empty dict.
      - All IDs (enrollment_id, campaign_id, org_id, etc.) are optional.
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

    # Sometimes Synthflow nests under call.metadata / request.metadata, etc.
    call = data.get("call") or {}
    call_metadata = call.get("metadata") or {}
    if isinstance(call_metadata.get("custom_variables"), list):
        candidates.append(call_metadata["custom_variables"])

    # New: lead.prompt_variables (where your org/enrollment/campaign IDs live)
    lead = data.get("lead") or {}
    prompt_vars = lead.get("prompt_variables") or {}
    if isinstance(prompt_vars, dict):
        for key, value in prompt_vars.items():
            custom_vars.setdefault(key, value)

    # Key/value style arrays
    for arr in candidates:
        for item in arr or []:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            value = item.get("value")
            if key:
                custom_vars.setdefault(key, value)

    # Also allow simple metadata-flattened vars
    for k in (
        "enrollment_id",
        "org_id",
        "reason_for_call",
        "campaign_id",
        "phone",
        "project_id",
        "contact_id",
    ):
        if k not in custom_vars and k in metadata:
            custom_vars[k] = metadata[k]
        if k not in custom_vars and k in call_metadata:
            custom_vars[k] = call_metadata[k]

    return custom_vars


def _lookup_smart_nurture_campaign_id(org_id: Optional[str]) -> Optional[str]:
    """
    Resolve the Smart Nurture campaign for this organization from `public.campaigns`:

      - organization_id = org_id
      - settings->>'category' = 'nurture'
      - settings->>'kind' = 'smart_nurture'

    Returns the campaign.id or None if not found.
    """
    if not org_id:
        log.info("[NurtureLookup] Skipping Smart Nurture lookup, no org_id provided.")
        return None

    try:
        resp = (
            supabase.table("campaigns")
            .select("id, settings, organization_id")
            .eq("organization_id", org_id)
            .filter("settings->>category", "eq", "nurture")
            .filter("settings->>kind", "eq", "smart_nurture")
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            log.info(
                "[NurtureLookup] No Smart Nurture campaign found for org_id=%s "
                "(category='nurture', kind='smart_nurture').",
                org_id,
            )
            return None

        campaign_id = rows[0]["id"]
        log.info(
            "[NurtureLookup] Resolved Smart Nurture campaign_id=%s for org_id=%s",
            campaign_id,
            org_id,
        )
        return campaign_id
    except Exception as ex:  # noqa: BLE001
        log.exception(
            "[NurtureLookup] Error looking up Smart Nurture campaign for org_id=%s: %s",
            org_id,
            ex,
        )
        return None


@router.post("/api/voice/transcript")
async def receive_transcript(request: Request):
    """
    Webhook endpoint that receives a payload from Synthflow.

    It supports BOTH:
      1) The full Synthflow call webhook payload (with `call`, `lead`, etc.)
      2) The compact custom-action payload we created:
            {
              "call_id": "...",
              "phone": "+1...",
              "transcript": "..."
            }

    Behavior:
      - Always logs the event in `message` (voice channel).
      - Derives status / missed-call state from whatever fields are present.
      - If it's a missed call *and* we have a phone, starts MissedCallFollowupWorkflow.
      - All IDs (enrollment, campaign, org, nurture) are optional.
    """
    data = await request.json()
    log.info("[Webhook] Received payload from Synthflow: %s", json.dumps(data)[:500])

    # ---------- Basic unpacking ----------
    call = data.get("call", {}) or {}
    provider_ref = call.get("call_id") or data.get("call_id") or data.get("_id")

    # Transcript & audio URL (top-level columns in the message table)
    transcript = call.get("transcript") or data.get("transcript") or ""
    audio_url = (
        call.get("recording_url")
        or data.get("recording_url")
        or data.get("audio_url")
    )

    # Optional metadata from Synthflow lead/contact object
    lead = data.get("lead", {}) or {}
    lead_name = lead.get("name")
    lead_phone = lead.get("phone_number") or lead.get("phone")

    # Optional custom variables (best-effort)
    custom_vars = _extract_custom_variables(data)
    enrollment_id = custom_vars.get("enrollment_id")
    campaign_id = custom_vars.get("campaign_id")
    org_id = custom_vars.get("org_id")
    reason_for_call = custom_vars.get("reason_for_call")
    project_id = custom_vars.get("project_id") or DEFAULT_PROJECT_ID

    if not provider_ref:
        log.warning(
            "[Webhook] Missing call_id in Synthflow payload: %s", list(data.keys())
        )
        return {"error": "Missing call_id"}, 400

    # ---------- Status / missed-call detection ----------

    raw_status = call.get("status") or data.get("status", "completed")
    normalized_status = "complete" if raw_status == "completed" else str(raw_status)

    call_result = (
        call.get("result")
        or call.get("disposition")
        or data.get("result")
        or data.get("disposition")
        or normalized_status
    )
    call_result = (call_result or "").lower().strip()

    base_missed = call_result in MISSED_CALL_STATUSES
    substring_missed = any(
        token in call_result
        for token in ("voicemail", "no_answer", "not_answered", "missed")
    )
    is_missed_call = base_missed or substring_missed

    status = call_result or normalized_status

    log.info(
        "[Webhook] Parsed call_id=%s | phone=%s | raw_status=%s | call_result=%s | "
        "is_missed_call=%s | status=%s | enrollment_id=%s | campaign_id=%s | org_id=%s",
        provider_ref,
        lead_phone,
        raw_status,
        call_result,
        is_missed_call,
        status,
        enrollment_id,
        campaign_id,
        org_id,
    )

    # ---------- Derive phone for follow-up ----------
    phone_for_followup = (
        lead_phone
        or custom_vars.get("phone")
        or data.get("phone")
        or data.get("phone_number")
        or call.get("to")
        or call.get("phone")
    )

    # ---------- Build content payload for DB ----------
    content = {
        "transcript": transcript,
        "audio_url": audio_url,
        "raw_payload": data,
        "raw_status": raw_status,
        "normalized_status": normalized_status,
        "call_result": call_result,
        "is_missed_call": is_missed_call,
        "campaign_id": campaign_id,
        "reason_for_call": reason_for_call,
        "org_id": org_id,
        "phone_for_followup": phone_for_followup,
        "status": status,
    }

    now = datetime.datetime.now(datetime.UTC).isoformat()
    record = {
        "project_id": project_id,
        "enrollment_id": enrollment_id,
        "channel": "voice",
        "direction": "inbound",
        "provider_ref": provider_ref,
        "status": status,
        "content": content,
        "transcript": transcript,
        "audio_url": audio_url,
        "occurred_at": now,
        "created_at": now,
    }

    # ---------- Persist + start workflow (best-effort) ----------
    try:
        supabase.table("message").insert(record).execute()
        log.info(
            "✅ Stored voice transcript for call_id=%s (phone=%s, lead=%s, raw_status=%s, "
            "result=%s, missed=%s, status=%s)",
            provider_ref,
            phone_for_followup or lead_phone,
            lead_name,
            raw_status,
            call_result,
            is_missed_call,
            status,
        )

        # --- 🔥 Start Temporal missed-call workflow (optional fields tolerated) ---
        if is_missed_call and phone_for_followup:
            nurture_campaign_id = _lookup_smart_nurture_campaign_id(org_id)

            log.info(
                "[MissedCall] Starting MissedCallFollowupWorkflow for phone=%s "
                "(enrollment_id=%s, campaign_id=%s, org_id=%s, nurture_campaign_id=%s, "
                "task_queue=%s)",
                phone_for_followup,
                enrollment_id,
                campaign_id,
                org_id,
                nurture_campaign_id,
                TEMPORAL_TASK_QUEUE,
            )

            # Deterministic workflow ID so duplicate webhooks don't double-enroll
            workflow_id = f"missed-call-{enrollment_id}"

            try:
                temporal_client = await get_temporal_client()
                await temporal_client.start_workflow(
                    MissedCallFollowupWorkflow.run,
                    id=workflow_id,
                    task_queue=TEMPORAL_TASK_QUEUE,
                    args=[
                        phone_for_followup,
                        enrollment_id,
                        campaign_id,
                        nurture_campaign_id,
                    ],
                )
                log.info(
                    "[MissedCall] Started MissedCallFollowupWorkflow | workflow_id=%s",
                    workflow_id,
                )

            except WorkflowAlreadyStartedError:
                log.info(
                    "[MissedCall] Workflow already started, ignoring duplicate webhook | "
                    "workflow_id=%s",
                    workflow_id,
                )
        else:
            log.info(
                "[MissedCall] Not starting missed-call workflow: "
                "is_missed_call=%s, phone_for_followup=%s, enrollment_id=%s",
                is_missed_call,
                phone_for_followup,
                enrollment_id,
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
