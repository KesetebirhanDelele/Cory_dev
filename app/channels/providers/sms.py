# app/channels/providers/sms.py
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, Optional

import httpx

# This module is used in two ways:
#   1) sms_send activity imports it as:
#        from app.channels.providers import sms as sms_client
#      and calls:
#        await sms_client.send(to=..., body=..., idempotency_key=...)
#
#   2) The package __init__ does:
#        from .sms import send_sms_via_slicktext
#      for backwards compatibility.
#
# We implement BOTH: a low-level `send(...)` and a higher-level
# `send_sms_via_slicktext(...)` that can delegate to app.external.sms
# or fall back to Twilio / stub mode.

try:
    from app.external import sms as external_sms  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    external_sms = None  # type: ignore

logger = logging.getLogger(__name__)

__all__ = ["send", "send_sms_via_slicktext"]

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

# Twilio hard limit is 1600 characters for concatenated SMS body.
# We stay a bit under that for safety.
MAX_SMS_BODY_CHARS = 1500

# ---------------------------------------------------------------------------
# Mode + Twilio helpers
# ---------------------------------------------------------------------------

def _should_stub() -> bool:
    """
    Determine whether to run in stub/mock mode.

    Stub mode is TRUE when:
    - CORY_LIVE_CHANNELS != "1"
    - OR HANDOFF_FAKE_MODE is truthy
    """
    live_mode = os.getenv("CORY_LIVE_CHANNELS", "0") == "1"
    fake_mode = os.getenv("HANDOFF_FAKE_MODE") in {"1", "true", "True"}

    if not live_mode:
        logger.info("[sms] Using STUB MODE because CORY_LIVE_CHANNELS != 1")
    if fake_mode:
        logger.info("[sms] Using STUB MODE because HANDOFF_FAKE_MODE is enabled")

    return (not live_mode) or fake_mode


async def _twilio_send(
    *,
    to: str,
    body: str,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Perform the actual HTTP call to Twilio's Messages API.
    """

    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    messaging_sid = os.getenv("TWILIO_MESSAGING_SERVICE_SID")
    from_number = os.getenv("TWILIO_FROM_NUMBER")

    if not account_sid or not auth_token:
        raise RuntimeError("TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN is missing")

    if not messaging_sid and not from_number:
        raise RuntimeError(
            "Either TWILIO_MESSAGING_SERVICE_SID or TWILIO_FROM_NUMBER must be set"
        )

    # 🔹 NEW: enforce Twilio body length limit
    original_len = len(body)
    if original_len > MAX_SMS_BODY_CHARS:
        logger.warning(
            "SMS body length %d exceeds max %d; truncating before Twilio send",
            original_len,
            MAX_SMS_BODY_CHARS,
        )
        body = body[:MAX_SMS_BODY_CHARS]

    base_url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"

    payload: Dict[str, Any] = {
        "To": to,
        "Body": body,
    }
    if messaging_sid:
        payload["MessagingServiceSid"] = messaging_sid
    else:
        payload["From"] = from_number

    headers: Dict[str, str] = {}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            base_url,
            data=payload,
            auth=(account_sid, auth_token),
            headers=headers,
        )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(
                "Twilio SMS HTTP error | status=%s body=%s",
                e.response.status_code if e.response else "unknown",
                e.response.text if e.response else "no-body",
            )
            raise

        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Unexpected Twilio response format (not JSON dict)")

        return data


# ---------------------------------------------------------------------------
# Primary provider API used by Temporal activity
# ---------------------------------------------------------------------------

async def send(
    *,
    to: str,
    body: str,
    idempotency_key: Optional[str] = None,
) -> str:
    """
    Unified SMS send used by Temporal sms_send activity.

    Returns:
        provider_ref: a string identifier for the outbound message.
    """

    # Stub mode for local/dev unless explicitly enabled
    if _should_stub():
        logger.info("[MOCK SMS PROVIDER] to=%s body=%s", to, body)
        return f"mock-sms-{uuid.uuid4()}"

    # If a richer external client exists (e.g., SlickText wrapper), prefer it.
    if external_sms is not None and hasattr(external_sms, "send_sms"):
        try:
            result: Dict[str, Any] = await external_sms.send_sms(
                to=to,
                message=body,
                idempotency_key=idempotency_key,
            )
            provider_ref = (
                result.get("provider_ref")
                or result.get("message_id")
                or result.get("id")
                or result.get("sid")
            )
            if not provider_ref:
                provider_ref = f"live-sms-{uuid.uuid4()}"
            logger.info(
                "External SMS client sent | to=%s ref=%s",
                to,
                provider_ref,
            )
            return str(provider_ref)
        except Exception as e:
            logger.warning(
                "External SMS client failed, falling back to Twilio: %s", e
            )

    # Fallback: direct Twilio call
    data = await _twilio_send(to=to, body=body, idempotency_key=idempotency_key)

    provider_ref = data.get("sid") or data.get("message_sid")
    if not provider_ref:
        provider_ref = f"twilio-sms-{uuid.uuid4()}"

    logger.info(
        "Twilio SMS sent | to=%s sid=%s status=%s",
        to,
        provider_ref,
        data.get("status"),
    )
    return str(provider_ref)


# ---------------------------------------------------------------------------
# Backwards compatibility: send_sms_via_slicktext
# ---------------------------------------------------------------------------

async def send_sms_via_slicktext(
    to: str,
    body: str,
    *,
    sender_id: Optional[str] = None,
    org_id: Optional[str] = None,
    enrollment_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Backwards-compatible higher-level API.

    This exists so that app.channels.providers.__init__ can do:
        from .sms import send_sms_via_slicktext

    It delegates to app.external.sms.send_sms_via_slicktext if present,
    or uses `send()` (Twilio / stub) as a fallback.
    """
    meta = metadata or {}

    # Prefer a dedicated wrapper if it exists
    if external_sms is not None and hasattr(external_sms, "send_sms_via_slicktext"):
        return await external_sms.send_sms_via_slicktext(
            to=to,
            body=body,
            sender_id=sender_id,
            org_id=org_id,
            enrollment_id=enrollment_id,
            campaign_id=campaign_id,
            metadata=metadata,
        )

    # Otherwise, just send via our main provider function and wrap the result
    provider_ref = await send(to=to, body=body, idempotency_key=None)

    return {
        "channel": "sms",
            "status": "sent",
            "provider_ref": provider_ref,
            "enrollment_id": enrollment_id,
            "request": {"to": to, "body": body},
            "context": {
                "org_id": org_id,
                "campaign_id": campaign_id,
                "sender_id": sender_id,
                "metadata": meta,
            },
    }
