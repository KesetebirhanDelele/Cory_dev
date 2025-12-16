# app/channels/providers/voice.py

"""
Synthflow Voice Provider Adapter
-------------------------------------------
Handles outbound call initiation and webhook configuration
for Cory Admissions (via Synthflow Programmable Voice API).

Now supports:

- Dynamic prompt override:
    - Prefer vars["prompt"] as the full runtime prompt for Synthflow
    - Fallback to vars["script"] (for backward compatibility)
    - Fallback to DEFAULT_SCRIPT if neither is provided

- Automatic context variables:
    - org_id and enrollment_id are always injected into custom_variables
    - campaign_id and reason_for_call can be passed explicitly
    - Any other keys in vars (except prompt/script/lead_name) are passed as
      custom_variables so they can be referenced in the Synthflow agent
      and in the webhook payload.
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

# Base URL of THIS app (ngrok / local / prod), used to build the webhook URL
CALLBACK_BASE_URL = os.getenv("CALLBACK_BASE_URL", "https://f651ebabb4f7.ngrok-free.app")
# Path portion can be overridden without touching code, e.g. "/api/voice/transcript" or "/api/voice/events"
CALLBACK_PATH = os.getenv("SYNTHFLOW_CALLBACK_PATH", "/api/voice/transcript")

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
    """Normalize Synthflow API response status into our internal status."""
    if not resp_json:
        return "TEMPORARY_FAILURE"

    # If Synthflow returns a call id anywhere reasonable, treat it as "sent"
    if (
        resp_json.get("call_id")
        or resp_json.get("id")
        or resp_json.get("response", {}).get("call_id")
    ):
        return "sent"

    # Fall back to provider status or queued
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
    campaign_id: Optional[str] = None,
    reason_for_call: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Initiate an outbound voice call via Synthflow API.

    Args:
        org_id: Organization ID (informational; also injected into custom_variables)
        enrollment_id: Campaign enrollment ID (also injected into custom_variables)
        to: Target phone number (E.164 format)
        vars: Optional dict of contextual variables for the voice agent:
              - prompt: full dynamic prompt override for Synthflow (preferred)
              - script: legacy script text (mapped to prompt if present)
              - lead_name: student name for display
              - reason_for_call: short phrase for why Cory is calling
              - attempt: numeric attempt count (1, 2, ...)
              - campaign_id: can also be provided here
              - any other keys -> forwarded as custom_variables
        campaign_id: Optional explicit campaign_id (will be injected into vars/custom_variables
                     if not already present).
        reason_for_call: Optional explicit reason_for_call (will be injected into vars/custom_variables
                         if not already present).

    Notes:
        - org_id and enrollment_id are ALWAYS added to custom_variables so that
          downstream webhooks / workflows can correlate calls even if provider_ref
          is missing or for analytics.
    """
    if not SYNTHFLOW_KEY or not SYNTHFLOW_MODEL:
        raise RuntimeError("❌ Synthflow credentials not configured in environment")

    if not to:
        raise ValueError("❌ 'to' phone number is missing or invalid")

    # Make a copy so we don't mutate caller's dict
    vars = dict(vars or {})

    # Ensure identifiers are always present
    vars.setdefault("org_id", org_id)
    vars.setdefault("enrollment_id", enrollment_id)

    if campaign_id is not None and "campaign_id" not in vars:
        vars["campaign_id"] = campaign_id

    if reason_for_call is not None and "reason_for_call" not in vars:
        vars["reason_for_call"] = reason_for_call

    callback_url: Optional[str] = None
    if CALLBACK_BASE_URL:
        callback_url = f"{CALLBACK_BASE_URL.rstrip('/')}{CALLBACK_PATH}"

    # 🔥 Dynamic prompt override:
    # 1) Prefer explicit vars["prompt"]
    # 2) Fallback to vars["script"] (legacy)
    # 3) Fallback to DEFAULT_SCRIPT
    dynamic_prompt: Optional[str] = vars.get("prompt")
    if not dynamic_prompt:
        legacy_script = vars.get("script")
        dynamic_prompt = legacy_script or DEFAULT_SCRIPT

    # Use lead_name for the call "name" if provided; otherwise tag with enrollment
    lead_name = vars.get("lead_name")
    display_name = lead_name or f"Enrollment-{enrollment_id}"

    # Build custom_variables from vars, excluding fields we handle separately
    excluded_keys = {"prompt", "script", "lead_name"}
    custom_variables = [
        {"key": k, "value": v}
        for k, v in vars.items()
        if k not in excluded_keys
    ]

    # ✅ Synthflow payload using dynamic prompt override
    payload: Dict[str, Any] = {
        "model_id": SYNTHFLOW_MODEL,
        "phone": to,
        "name": display_name,
        # Synthflow expects the "prompt" field for runtime prompt override.
        "prompt": dynamic_prompt,
    }

    # Only include custom_variables if we actually have some
    if custom_variables:
        payload["custom_variables"] = custom_variables

    # Synthflow requires external_webhook_url for call event callbacks
    if callback_url:
        payload["external_webhook_url"] = callback_url

    headers = {
        "Authorization": f"Bearer {SYNTHFLOW_KEY}",
        "Content-Type": "application/json",
    }

    result: Dict[str, Any] = {
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
                "✅ [Synthflow] Call initiated | org=%s | enrollment=%s | to=%s | provider_ref=%s | status=%s",
                org_id,
                enrollment_id,
                to,
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

    except Exception as ex:  # noqa: BLE001
        log.exception("[Synthflow] Unexpected error: %s", ex)
        result["status"] = "TEMPORARY_FAILURE"
        result["response_raw"] = {"error": str(ex)}
        return result
