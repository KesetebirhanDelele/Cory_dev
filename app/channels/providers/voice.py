# app/channels/providers/voice.py
import os
import uuid
import httpx
import logging

logger = logging.getLogger("cory.voice")

async def send_voice(org_id: str, enrollment_id: str, text: str, *, to: str) -> dict:
    """Send a voice message (Synthflow adapter, mock/live)."""
    live_mode = os.getenv("CORY_LIVE_CHANNELS") == "1"

    # --- Mock / Stub mode ---
    if not live_mode:
        return {
            "channel": "voice",
            "enrollment_id": enrollment_id,
            "provider_ref": f"mock-voice-{uuid.uuid4().hex[:8]}",
            "status": "queued",
            "request": {"org_id": org_id, "text": text, "to": to},
        }

    # --- Live / Real mode ---
    try:
        async with httpx.AsyncClient() as client:
            # Dummy Synthflow-like API call (mocked in tests)
            resp = await client.post(
                "https://api.synthflow.ai/v1/call",
                json={"to": to, "text": text, "org_id": org_id},
            )
            resp.raise_for_status()
            data = resp.json()

            return {
                "channel": "voice",
                "enrollment_id": enrollment_id,
                "provider_ref": data.get("call_id", f"live-voice-{uuid.uuid4().hex[:8]}"),
                "status": "sent",
                "request": {"org_id": org_id, "text": text, "to": to},
            }

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error sending voice call: {e}")
        code = e.response.status_code
        if code in (429, 503):
            status = "RATE_LIMIT" if code == 429 else "TEMPORARY_FAILURE"
        else:
            status = "PERMANENT_FAILURE"
    except Exception as e:
        logger.error(f"Unexpected error sending voice call: {type(e).__name__} - {e}")
        status = "TEMPORARY_FAILURE"

    return {
        "channel": "voice",
        "enrollment_id": enrollment_id,
        "provider_ref": None,
        "status": status,
        "request": {"org_id": org_id, "text": text, "to": to},
    }
