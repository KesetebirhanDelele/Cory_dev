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

    # ✅ Correctly unwrap Synthflow JSON structure
    call = data.get("call", {})
    provider_ref = call.get("call_id")
    transcript = call.get("transcript", "")
    audio_url = call.get("recording_url")

    # Optional metadata
    lead_name = data.get("lead", {}).get("name")
    enrollment_id = None
    if lead_name and lead_name.startswith("Enrollment-"):
        enrollment_id = lead_name.replace("Enrollment-", "")

    project_id = os.getenv("DEFAULT_PROJECT_ID")

    if not provider_ref:
        log.warning(f"[Webhook] Missing call_id in Synthflow payload: {data.keys()}")
        return {"error": "Missing call_id"}, 400

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
        "status": data.get("status", "completed"),
        "content": json.dumps(content),
        "occurred_at": now,
        "created_at": now,
    }

    try:
        res = supabase.table("message").insert(record).execute()
        log.info(f"✅ Stored voice transcript for call_id={provider_ref}")
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
