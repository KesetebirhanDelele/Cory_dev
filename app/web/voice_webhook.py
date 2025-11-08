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
    Webhook endpoint that receives a transcript payload from Synthflow (or another voice provider)
    and logs it into the `message` table. Handles duplicate provider_ref gracefully.
    """

    data = await request.json()
    provider_ref = data.get("call_id")
    transcript = data.get("transcript_text", "")
    enrollment_id = data.get("metadata", {}).get("enrollment_id")
    project_id = data.get("metadata", {}).get("project_id")
    audio_url = data.get("audio_url")

    if not provider_ref:
        return {"error": "Missing call_id"}, 400

    content = {
        "transcript": transcript,
        "audio_url": audio_url,
        "raw_payload": data
    }

    now = datetime.datetime.now(datetime.UTC).isoformat()

    record = {
        "project_id": project_id or os.getenv("DEFAULT_PROJECT_ID"),
        "enrollment_id": enrollment_id,
        "channel": "voice",
        "direction": "inbound",
        "provider_ref": provider_ref,
        "status": "complete",
        "content": json.dumps(content),
        "occurred_at": now,
        "created_at": now
    }

    try:
        response = supabase.table("message").insert(record).execute()
        return {"success": True, "provider_ref": provider_ref}

    except APIError as e:
        # Handle duplicate constraint gracefully
        if "duplicate key value violates unique constraint" in str(e):
            log.warning(f"[Webhook] Duplicate provider_ref={provider_ref} ignored.")
            return {
                "success": True,
                "provider_ref": provider_ref,
                "duplicate": True
            }

        log.exception("[Webhook] Supabase API error: %s", e)
        return {"error": str(e)}, 500

    except Exception as ex:
        log.exception("[Webhook] Unexpected error: %s", ex)
        return {"error": str(ex)}, 500
