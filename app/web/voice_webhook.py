# app/web/voice_webhook.py

from fastapi import APIRouter, Request
from supabase import create_client
import os
import datetime
import json
import logging
from postgrest.exceptions import APIError

router = APIRouter()
log = logging.getLogger("cory.voice.webhook")

# Initialize Supabase client
supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
)


@router.post("/api/voice/transcript")
async def receive_transcript(request: Request):
    """
    Webhook endpoint that receives a transcript payload from Synthflow
    and logs it into the `message` table.

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
        "transcript": "...",
        "recording_url": "https://..."
      },
      "analysis": { ... },
      "metadata": { ... }
    }
    """
    data = await request.json()
    log.info("[Webhook] Received payload from Synthflow: %s", json.dumps(data)[:500])

    # ✅ Unwrap Synthflow JSON structure
    call = data.get("call", {}) or {}
    provider_ref = call.get("call_id") or data.get("call_id")

    # Transcript & audio URL (what you want in top-level columns)
    transcript = (
        call.get("transcript")
        or data.get("transcript")
        or ""
    )
    audio_url = (
        call.get("recording_url")
        or data.get("recording_url")
        or data.get("audio_url")
    )

    # Optional metadata: used for logging/diagnostics
    lead = data.get("lead", {}) or {}
    lead_name = lead.get("name")
    lead_phone = lead.get("phone_number")

    # For now we don't try to infer enrollment_id from lead name/phone.
    # You can wire this later via external_id / metadata.
    enrollment_id = None
    project_id = os.getenv("DEFAULT_PROJECT_ID")

    if not provider_ref:
        log.warning("[Webhook] Missing call_id in Synthflow payload: %s", list(data.keys()))
        return {"error": "Missing call_id"}, 400

    # Normalize status so it lines up with VoiceConversationAgent._collect_transcript,
    # which currently checks for "complete".
    raw_status = call.get("status") or data.get("status", "completed")
    normalized_status = "complete" if raw_status == "completed" else raw_status

    # Store rich content (matches what you saw in your SELECT)
    content = {
        "transcript": transcript,
        "audio_url": audio_url,
        "raw_payload": data,
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
        # ❗ IMPORTANT: content stays as a JSON object, not a string
        "content": content,
        "transcript": transcript,   # 🔥 populate column
        "audio_url": audio_url,     # 🔥 populate column
        "occurred_at": now,
        "created_at": now,
    }

    try:
        supabase.table("message").insert(record).execute()
        log.info(
            "✅ Stored voice transcript for call_id=%s (phone=%s, lead=%s, status=%s)",
            provider_ref,
            lead_phone,
            lead_name,
            normalized_status,
        )
        return {"success": True, "provider_ref": provider_ref}

    except APIError as e:
        if "duplicate key value violates unique constraint" in str(e):
            log.warning("[Webhook] Duplicate provider_ref=%s ignored.", provider_ref)
            return {"success": True, "duplicate": True, "provider_ref": provider_ref}
        log.exception("[Webhook] Supabase API error")
        return {"error": str(e)}, 500

    except Exception as ex:
        log.exception("[Webhook] Unexpected error while inserting transcript")
        return {"error": str(ex)}, 500
