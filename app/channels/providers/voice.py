# app/channels/providers/voice/synthflow_adapter.py
"""
Synthflow Voice Provider Adapter
Handles outbound call initiation and webhook configuration for Cory Admissions.
"""

import os
import logging
from typing import Optional, Dict, Any
import httpx
from dotenv import load_dotenv

# --- Load environment variables early ---
load_dotenv()

log = logging.getLogger("cory.voice.synthflow")

# ================================================================
# Synthflow Configuration
# ================================================================
SYNTHFLOW_KEY = os.getenv("SYNTHFLOW_API_KEY")
SYNTHFLOW_MODEL = os.getenv("SYNTHFLOW_MODEL_ID")
SYNTHFLOW_URL = os.getenv("SYNTHFLOW_API_URL", "https://api.synthflow.ai/v2/calls")
CALLBACK_BASE_URL = os.getenv("CALLBACK_BASE_URL")  # e.g., https://abc123.ngrok.io
SYNTHFLOW_SCRIPT = os.getenv(
    "SYNTHFLOW_SCRIPT", "Hello, this is Cory Admissions calling to follow up."
)

# Optional: toggle between test/live mode
LIVE = os.getenv("SYNTHFLOW_LIVE", "true").lower() in ("1", "true", "yes")

# ================================================================
# Helper: map status from Synthflow response
# ================================================================
def map_synthflow_status(resp_json: Dict[str, Any]) -> str:
    if not resp_json:
        return "TEMPORARY_FAILURE"
    if resp_json.get("call_id") or resp_json.get("id"):
        return "sent"
    return resp_json.get("status", "queued")


# ================================================================
# Main API Function
# ================================================================
async def send_voice_call(
    org_id: str,
    enrollment_id: str,
    to: str,
    *,
    vars: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Initiate a voice call via Synthflow API.

    Args:
        org_id: Organization ID
        enrollment_id: Campaign enrollment ID
        to: Target phone number
        vars: Optional custom variables injected into the Synthflow model context
    """
    if not SYNTHFLOW_KEY or not SYNTHFLOW_MODEL:
        raise RuntimeError("❌ Synthflow credentials not configured in environment")

    # ------------------------------------------------------------
    # Build payload for Synthflow API
    # ------------------------------------------------------------
    payload = {
        "model_id": SYNTHFLOW_MODEL,
        "phone": to,
        "name": enrollment_id,
        "custom_variables": vars or {},
        "script": SYNTHFLOW_SCRIPT,
    }

    if CALLBACK_BASE_URL:
        payload["webhook_url"] = f"{CALLBACK_BASE_URL}/voice/callback"

    # Standardized result shell
    result = {
        "channel": "voice",
        "enrollment_id": enrollment_id,
        "provider_ref": None,
        "status": "queued",
        "request": payload,
        "response_raw": None,
    }

    headers = {
        "Authorization": f"Bearer {SYNTHFLOW_KEY}",
        "Content-Type": "application/json",
    }

    # ------------------------------------------------------------
    # Make API call
    # ------------------------------------------------------------
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(SYNTHFLOW_URL, json=payload, headers=headers)
            log.info("[Synthflow] POST %s -> %s", SYNTHFLOW_URL, resp.status_code)
            resp.raise_for_status()

            data = resp.json()
            result["response_raw"] = data

            provider_ref = (
                data.get("call_id") or data.get("id") or data.get("message_id")
            )
            result["provider_ref"] = provider_ref
            result["status"] = map_synthflow_status(data)

            log.info(
                "[Synthflow] Call initiated | lead=%s provider_ref=%s status=%s",
                enrollment_id,
                provider_ref,
                result["status"],
            )
            return result

    except httpx.HTTPStatusError as e:
        code = getattr(e.response, "status_code", None)
        log.exception("[Synthflow] HTTP error: %s", e)
        result["status"] = "RATE_LIMIT" if code == 429 else "TEMPORARY_FAILURE"
        result["response_raw"] = {"error": str(e), "status_code": code}
        return result

    except Exception as ex:
        log.exception("[Synthflow] Unexpected error: %s", ex)
        result["status"] = "TEMPORARY_FAILURE"
        result["response_raw"] = {"error": str(ex)}
        return result
