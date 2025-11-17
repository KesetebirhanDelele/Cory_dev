# app/channels/providers/voice.py
from __future__ import annotations

import os
import logging
from typing import Any, Dict

import httpx

log = logging.getLogger("cory.voice.provider")
log.setLevel(logging.INFO)


def _live_voice_enabled() -> bool:
    """
    Decide if live voice calls should be used.

    CORY_LIVE_CHANNELS examples:
      - "1"                => all live
      - "voice"            => live only for voice
      - "sms,voice"        => live for sms + voice
    Anything else => stub mode.
    """
    flag = os.getenv("CORY_LIVE_CHANNELS", "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return True
    return "voice" in {p.strip() for p in flag.split(",") if p.strip()}


async def send_voice(
    org_id: str,
    enrollment_id: str,
    script: str,
    *,
    to: str | None = None,
    vars: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Public adapter used by tests and activities.

    Stub mode:
      - Does NOT call external API
      - Returns status='queued' and provider_ref starting with 'mock-voice-'

    Live mode:
      - Calls Synthflow via HTTP
      - On success: status='sent', provider_ref = call_id
      - On HTTP errors: status in {'RATE_LIMIT', 'TEMPORARY_FAILURE', 'PERMANENT_FAILURE'}
    """
    vars = vars or {}

    # ------------------------------------------------------------------ stub mode
    if not _live_voice_enabled():
        log.info(
            "🧪 [voice] stub mode: org=%s enrollment=%s to=%s",
            org_id,
            enrollment_id,
            to,
        )
        return {
            "status": "queued",
            "channel": "voice",
            "enrollment_id": enrollment_id,
            "to": to,
            "request": {
                "org_id": org_id,
                "script": script,
                "vars": vars,
            },
            # IMPORTANT: tests expect this prefix
            "provider_ref": f"mock-voice-{enrollment_id}",
        }

    # ------------------------------------------------------------------ live mode
    base_url = os.getenv("SYNTHFLOW_URL", "https://api.synthflow.ai")
    api_key = os.getenv("SYNTHFLOW_API_KEY", "test-key")

    payload = {
        "org_id": org_id,
        "enrollment_id": enrollment_id,
        "to": to,
        "script": script,
        "vars": vars,
    }

    try:
        # NOTE: no arguments, so DummyClient() from tests is compatible
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{base_url}/v1/call",
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            body = resp.json() or {}
            call_id = body.get("call_id") or body.get("id")

        log.info(
            "📞 [voice] live call started org=%s enrollment=%s call_id=%s",
            org_id,
            enrollment_id,
            call_id,
        )
        return {
            "status": "sent",
            "channel": "voice",
            "enrollment_id": enrollment_id,
            "to": to,
            "provider_ref": call_id,
            "request": payload,
            "response": body,
        }

    except httpx.HTTPStatusError as exc:
        # Map HTTP errors to the taxonomy expected by tests
        status_code = getattr(exc.response, "status_code", None) or 500
        if status_code == 429:
            mapped = "RATE_LIMIT"
        elif status_code >= 500:
            mapped = "TEMPORARY_FAILURE"
        else:
            mapped = "PERMANENT_FAILURE"

        log.warning(
            "❌ [voice] HTTPStatusError status=%s mapped=%s",
            status_code,
            mapped,
        )
        return {
            "status": mapped,
            "channel": "voice",
            "enrollment_id": enrollment_id,
            "to": to,
        }
    except Exception as exc:  # noqa: BLE001
        # Tests don't assert on this branch, but keep a sensible default
        log.exception("❌ [voice] unexpected error starting call: %s", exc)
        return {
            "status": "TEMPORARY_FAILURE",
            "channel": "voice",
            "enrollment_id": enrollment_id,
            "to": to,
        }


# Convenience wrapper used by VoiceConversationAgent / dialer
async def send_voice_call(
    org_id: str,
    enrollment_id: str,
    phone: str,
    vars: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Thin wrapper so higher-level code can stick with send_voice_call().
    """
    vars = vars or {}
    script = vars.get("script", "")
    return await send_voice(org_id, enrollment_id, script, to=phone, vars=vars)
