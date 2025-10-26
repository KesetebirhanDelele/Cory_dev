# app/channels/providers/sms.py
import os
import uuid
import httpx
from typing import Optional, Dict, Any

__all__ = ["send_sms", "send_sms_via_slicktext"]

def _should_stub() -> bool:
    """
    Stub mode if:
      - CORY_LIVE_CHANNELS != "1" (default), OR
      - HANDOFF_FAKE_MODE in {"1","true","True"}
    """
    live_mode = os.getenv("CORY_LIVE_CHANNELS", "0") == "1"
    fake_mode = os.getenv("HANDOFF_FAKE_MODE") in {"1", "true", "True"}
    return (not live_mode) or fake_mode


async def _post_slicktext(to: Optional[str], body: str) -> Dict[str, Any]:
    """
    Perform the actual HTTP call to SlickText.
    Separated for testability and to keep send_sms focused on orchestration.
    """
    api_key = os.getenv("SLICKTEXT_API_KEY", "demo-key")
    base_url = os.getenv("SLICKTEXT_API_URL", "https://api.slicktext.com/v1/messages")

    # Allow simulation of provider timeout/expiry in tests
    if os.getenv("HANDOFF_TIMEOUT_STATUS") == "expired":
        # Raise a timeout-like error to hit the generic exception path below
        raise httpx.TimeoutException("Simulated provider timeout/expiry")

    Client = getattr(httpx, "AsyncClient", None)
    if Client is None:
        raise RuntimeError("httpx.AsyncClient missing")

    # Some dummy clients used in tests may not accept kwargs
    try:
        client_instance = Client(timeout=10.0)
    except TypeError:
        client_instance = Client()

    async with client_instance as client:
        response = await client.post(
            base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"to": to, "body": body},
        )

        # On real httpx.Response this exists; in tests it may be a stub
        if hasattr(response, "raise_for_status"):
            response.raise_for_status()

        data = response.json() if hasattr(response, "json") else {}
        return data if isinstance(data, dict) else {}


async def send_sms(
    org_id: str,
    enrollment_id: str,
    body: str,
    *,
    to: Optional[str] = None,
) -> Dict[str, Any]:
    """Send SMS via SlickText (live or stub mode)."""
    # 🧪 Stub mode (default unless CORY_LIVE_CHANNELS=1)
    if _should_stub():
        return {
            "channel": "sms",
            "enrollment_id": enrollment_id,
            "provider_ref": f"stub-sms-{enrollment_id}",
            "status": "queued",
            "request": {"to": to, "body": body},
        }

    try:
        data = await _post_slicktext(to=to, body=body)

        # ✅ Happy path: mark message as sent
        return {
            "channel": "sms",
            "enrollment_id": enrollment_id,
            "provider_ref": data.get("message_id", f"live-sms-{uuid.uuid4()}"),
            "status": "sent",
            "request": {"to": to, "body": body},
        }

    except httpx.HTTPStatusError as e:
        code = getattr(e.response, "status_code", 500)
        status_map = {
            429: "RATE_LIMIT",
            500: "TEMPORARY_FAILURE",
            503: "TEMPORARY_FAILURE",
            400: "PERMANENT_FAILURE",
            403: "PERMANENT_FAILURE",
        }
        mapped_status = status_map.get(code, "TEMPORARY_FAILURE")
        return {
            "channel": "sms",
            "enrollment_id": enrollment_id,
            "provider_ref": None,
            "status": mapped_status,
            "request": {"to": to, "body": body},
        }

    except Exception as ex:
        # Keep logging minimal to avoid leaking secrets
        print(f"[send_sms] Unexpected error: {type(ex).__name__} - {ex}")
        return {
            "channel": "sms",
            "enrollment_id": enrollment_id,
            "provider_ref": None,
            "status": "TEMPORARY_FAILURE",
            "request": {"to": to, "body": body},
        }


# ---------------------------------------------------------------------------
# Compatibility wrapper expected by activities:
# from app.channels.providers.sms import send_sms_via_slicktext
#
# This accepts a more "provider-oriented" signature but delegates to send_sms.
# ---------------------------------------------------------------------------
async def send_sms_via_slicktext(
    to: str,
    body: str,
    *,
    sender_id: Optional[str] = None,        # reserved for future use
    org_id: Optional[str] = None,
    enrollment_id: Optional[str] = None,
    campaign_id: Optional[str] = None,      # reserved for future use
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Async wrapper that aligns with imports elsewhere:
      - If org_id/enrollment_id are not provided, fall back to metadata.
    """
    meta = metadata or {}
    if "trace_id" not in meta:
        from app.common.tracing import get_trace_id
        tid = get_trace_id()
        if tid:
            meta["trace_id"] = tid
    resolved_org_id = org_id or meta.get("org_id", "unknown-org")
    resolved_enrollment_id = enrollment_id or meta.get("enrollment_id", "unknown-enrollment")

    result = await send_sms(
        resolved_org_id,
        resolved_enrollment_id,
        body,
        to=to,
    )

    # Non-breaking addition: echo through optional context so callers can correlate
    # (won't affect existing consumers that ignore it)
    result.setdefault("context", {})
    result["context"].update({
        "org_id": resolved_org_id,
        "campaign_id": campaign_id,
        "sender_id": sender_id,
        **({} if not metadata else {"metadata": metadata}),
    })
    return result
