# app/channels/providers/voice/synthflow_adapter.py
import os, logging
from typing import Optional, Dict, Any
import httpx
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

log = logging.getLogger("cory.voice.synthflow")

# Load credentials and config
SYNTHFLOW_KEY = os.getenv("SYNTHFLOW_API_KEY")
SYNTHFLOW_MODEL = os.getenv("SYNTHFLOW_MODEL_ID")
SYNTHFLOW_URL = os.getenv("SYNTHFLOW_API_URL", "https://api.synthflow.ai/v2/calls")
CALLBACK_BASE_URL = os.getenv("CALLBACK_BASE_URL")  # e.g., https://abc.ngrok.io

# Force LIVE mode for testing — change back to env-driven after confirming
LIVE = True  # ✅ Force live mode to ensure real call is sent

def map_synthflow_status(resp_json: Dict[str, Any]) -> str:
    if not resp_json:
        return "TEMPORARY_FAILURE"
    if resp_json.get("call_id") or resp_json.get("id"):
        return "sent"
    return "queued"

async def send_voice_call(org_id: str, enrollment_id: str, to: str, *, vars: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = {
        "model_id": SYNTHFLOW_MODEL,
        "phone": to,
        "name": enrollment_id,
        "custom_variables": vars or [],
        "script": "Hello, this is a test call from Synthflow.",  # ✅ Add this if required
    }

    if CALLBACK_BASE_URL:
        payload["webhook_url"] = f"{CALLBACK_BASE_URL}/voice/callback"

    result = {
        "channel": "voice",
        "enrollment_id": enrollment_id,
        "provider_ref": None,
        "status": "queued",
        "request": payload,
        "response_raw": None,
    }

    if not SYNTHFLOW_KEY or not SYNTHFLOW_MODEL:
        raise RuntimeError("Synthflow credentials not configured")

    headers = {
        "Authorization": f"Bearer {SYNTHFLOW_KEY}",
        "Content-Type": "application/json"
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(SYNTHFLOW_URL, json=payload, headers=headers)
            print("🔍 Synthflow response:", resp.text)  # Add this line
            resp.raise_for_status()
            data = resp.json()
            result["response_raw"] = data
            provider_ref = data.get("call_id") or data.get("id") or data.get("message_id")
            result["provider_ref"] = provider_ref
            result["status"] = map_synthflow_status(data)
            return result
    except httpx.HTTPStatusError as e:
        status_code = getattr(e.response, "status_code", None)
        log.exception("Synthflow HTTP error")
        result["status"] = "RATE_LIMIT" if status_code == 429 else "TEMPORARY_FAILURE"
        result["response_raw"] = {"error": str(e), "status_code": status_code}
        return result
    except Exception as ex:
        log.exception("Unexpected error calling Synthflow")
        result["status"] = "TEMPORARY_FAILURE"
        result["response_raw"] = {"error": str(ex)}
        return result