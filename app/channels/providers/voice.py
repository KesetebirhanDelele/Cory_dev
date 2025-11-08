# app/channels/providers/voice.py
"""
Synthflow Voice Provider Adapter
-------------------------------------------
Handles outbound call initiation and webhook configuration
for Cory Admissions (via Synthflow Programmable Voice API).
"""

import os
import json
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
SYNTHFLOW_API_URL = os.getenv("SYNTHFLOW_API_URL", "https://api.synthflow.ai/v2/calls")
CALLBACK_BASE_URL = os.getenv("CALLBACK_BASE_URL", "https://f651ebabb4f7.ngrok-free.app")

DEFAULT_SCRIPT = os.getenv(
    "SYNTHFLOW_SCRIPT",
    "Hi, this is Cory Admissions calling to follow up on your application. "
    "We’re excited about your interest and just wanted to connect with you!",
)

LIVE = os.getenv("SYNTHFLOW_LIVE", "true").lower() in ("1", "true", "yes")


# ================================================================
# Helper: map status from Synthflow response
# ================================================================
def map_synthflow_status(resp_json: Dict[str, Any]) -> str:
    """Normalize Synthflow API response status."""
    if not resp_json:
        return "TEMPORARY_FAILURE"
    if resp_json.get("call_id") or resp_json.get("id"):
        return "sent"
    return resp_json.get("status", "queued")


# ================================================================
# Main Function: Send Voice Call
# ================================================================
async def send_voice_call(
    org_id: str,
    enrollment_id: str,
    to: str,
    *,
    vars: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Initiate an outbound voice call via Synthflow API.

    Args:
        org_id: Organization ID
        enrollment_id: Campaign enrollment ID
        to: Target phone number (E.164 format)
        vars: Optional dict of contextual variables for the voice agent
    """
    if not SYNTHFLOW_KEY or not SYNTHFLOW_MODEL:
        raise RuntimeError("❌ Synthflow credentials not configured in environment")

    if not to:
        raise ValueError("❌ 'to' phone number is missing or invalid")

    callback_url = f"{CALLBACK_BASE_URL.rstrip('/')}/api/voice/transcript" if CALLBACK_BASE_URL else None

    # ✅ Use custom campaign message if available
    script_text = (vars or {}).get("script") or DEFAULT_SCRIPT

    # ✅ Correct Synthflow payload
    payload = {
        "model_id": SYNTHFLOW_MODEL,
        "phone": to,
        "name": f"Enrollment-{enrollment_id}",
        "script": script_text,
        "custom_variables": [
        {"key": k, "value": v} for k, v in (vars or {}).items()
        ]
    }

    # ✅ Synthflow requires the key `external_webhook_url`
    if callback_url:
        payload["external_webhook_url"] = callback_url

    headers = {
        "Authorization": f"Bearer {SYNTHFLOW_KEY}",
        "Content-Type": "application/json",
    }

    result = {
        "channel": "voice",
        "enrollment_id": enrollment_id,
        "provider_ref": None,
        "status": "queued",
        "request": payload,
        "response_raw": None,
    }

    api_endpoint = SYNTHFLOW_API_URL.rstrip("/")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(api_endpoint, json=payload, headers=headers)
            log.info("[Synthflow] POST %s -> %s", api_endpoint, resp.status_code)
            log.info("[Synthflow] Request payload:\n%s", json.dumps(payload, indent=2))
            log.info("[Synthflow] Response body:\n%s", resp.text)

            resp.raise_for_status()

            data = resp.json()
            result["response_raw"] = data
            provider_ref = (
                data.get("id")
                or data.get("call_id")
                or data.get("response", {}).get("call_id")
            )
            result["provider_ref"] = provider_ref
            result["status"] = map_synthflow_status(data)

            log.info(
                "✅ [Synthflow] Call initiated | enrollment=%s | provider_ref=%s | status=%s",
                enrollment_id,
                provider_ref,
                result["status"],
            )

            return result

    except httpx.HTTPStatusError as e:
        code = getattr(e.response, "status_code", None)
        log.error("[Synthflow] HTTP error %s: %s", code, e)
        log.error("[Synthflow] Response: %s", getattr(e.response, "text", ""))
        result["status"] = "RATE_LIMIT" if code == 429 else "TEMPORARY_FAILURE"
        result["response_raw"] = {"error": str(e), "status_code": code}
        return result

    except Exception as ex:
        log.exception("[Synthflow] Unexpected error: %s", ex)
        result["status"] = "TEMPORARY_FAILURE"
        result["response_raw"] = {"error": str(ex)}
        return result
