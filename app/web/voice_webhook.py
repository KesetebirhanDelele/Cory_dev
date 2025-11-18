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
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")
)

@router.post("/api/voice/transcript")
async def receive_transcript(request: Request):
    """
    Webhook endpoint that receives a transcript payload from Synthflow
    and logs it into the `message` table.
    """
    data = await request.json()
    log.info(f"[Webhook] Received payload from Synthflow: {json.dumps(data)[:500]}")

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

    # Optional metadata: we no longer try to parse enrollment_id from lead name
    lead = data.get("lead", {}) or {}
    lead_name = lead.get("name")
    lead_phone = lead.get("phone_number")

    enrollment_id = None  # can be wired later via external_id/metadata if needed
    project_id = os.getenv("DEFAULT_PROJECT_ID")

    if not provider_ref:
        log.warning(f"[Webhook] Missing call_id in Synthflow payload: {list(data.keys())}")
        return {"error": "Missing call_id"}, 400

    # Store rich content (what you saw in your SELECT)
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
        # Prefer call.status if present, else top-level status, else completed
        "status": call.get("status") or data.get("status", "completed"),
        # ❗ IMPORTANT: pass dict, not json.dumps(...)
        "content": content,
        "transcript": transcript,   # 🔥 populate column
        "audio_url": audio_url,     # 🔥 populate column
        "occurred_at": now,
        "created_at": now,
    }

    try:
        res = supabase.table("message").insert(record).execute()
        log.info(
            "✅ Stored voice transcript for call_id=%s (phone=%s, lead=%s)",
            provider_ref,
            lead_phone,
            lead_name,
        )
        return {"success": True, "provider_ref": provider_ref}

    except APIError as e:
        if "duplicate key value violates unique constraint" in str(e):
            log.warning(f"[Webhook] Duplicate provider_ref={provider_ref} ignored.")
            return {"success": True, "duplicate": True, "provider_ref": provider_ref}
        log.exception("[Webhook] Supabase API error")
        return {"error": str(e)}, 500

    except Exception as ex:
        log.exception("[Webhook] Unexpected error while inserting transcript")
        return {"error": str(ex)}, 500
