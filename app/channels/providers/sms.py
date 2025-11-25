import os
import uuid
import httpx
from typing import Optional, Dict, Any

__all__ = ["send_sms", "send_sms_via_slicktext"]


def _should_stub() -> bool:
    """
    Determines if Cory should operate in stub mode.
    
    Stub mode is TRUE when:
    - CORY_LIVE_CHANNELS != "1"
    - OR HANDOFF_FAKE_MODE is truthy
    """
    live_mode = os.getenv("CORY_LIVE_CHANNELS", "0") == "1"
    fake_mode = os.getenv("HANDOFF_FAKE_MODE") in {"1", "true", "True"}

    # Explicit console signal for debugging
    if not live_mode:
        print("[sms] Using STUB MODE because CORY_LIVE_CHANNELS != 1")
    if fake_mode:
        print("[sms] Using STUB MODE because HANDOFF_FAKE_MODE is enabled")

    return (not live_mode) or fake_mode


async def _post_slicktext(to: Optional[str], body: str) -> Dict[str, Any]:
    """
    Perform actual HTTP call to SlickText's Message API.
    """
    api_key = os.getenv("SLICKTEXT_API_KEY")
    base_url = os.getenv("SLICKTEXT_API_URL", "https://api.slicktext.com/v1/messages")

    if not api_key:
        raise RuntimeError("SLICKTEXT_API_KEY is missing. Cannot send real SMS.")

    # Simulate provider timeout, if test flag provided
    if os.getenv("HANDOFF_TIMEOUT_STATUS") == "expired":
        raise httpx.TimeoutException("Simulated provider timeout/expiry")

    Client = getattr(httpx, "AsyncClient", None)
    if Client is None:
        raise RuntimeError("httpx.AsyncClient missing - httpx not installed correctly")

    try:
        client_instance = Client(timeout=15.0)
    except TypeError:
        client_instance = Client()

    payload = {
        "to": to,
        "body": body,
    }

    async with client_instance as client:
        response = await client.post(
            base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

        # If this is a real httpx.Response object
        if hasattr(response, "raise_for_status"):
            response.raise_for_status()

        data = response.json() if hasattr(response, "json") else {}

        if not isinstance(data, dict):
            return {}

        return data


async def send_sms(
    org_id: str,
    enrollment_id: str,
    body: str,
    *,
    to: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send SMS via SlickText, respecting stub mode and mapping provider responses.
    """

    # Stub mode = default unless CORY_LIVE_CHANNELS=1 and HANDOFF_FAKE_MODE=0
    if _should_stub():
        return {
            "channel": "sms",
            "status": "queued",
            "provider_ref": f"stub-sms-{uuid.uuid4()}",
            "enrollment_id": enrollment_id,
            "request": {"to": to, "body": body},
        }

    # Live mode:
    try:
        provider_data = await _post_slicktext(to=to, body=body)

        provider_ref = provider_data.get("message_id") or f"live-sms-{uuid.uuid4()}"

        return {
            "channel": "sms",
            "status": "sent",
            "provider_ref": provider_ref,
            "enrollment_id": enrollment_id,
            "request": {"to": to, "body": body},
            "provider_raw": provider_data,
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

        print(f"[sms] SlickText HTTP error: {code}")

        return {
            "channel": "sms",
            "status": mapped_status,
            "provider_ref": None,
            "enrollment_id": enrollment_id,
            "request": {"to": to, "body": body},
        }

    except Exception as ex:
        # Prevent secret leakage
        print(f"[sms] Unexpected SMS error: {type(ex).__name__} - {ex}")

        return {
            "channel": "sms",
            "status": "TEMPORARY_FAILURE",
            "provider_ref": None,
            "enrollment_id": enrollment_id,
            "request": {"to": to, "body": body},
        }


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
    Wrapper for compatibility — delegates to send_sms() with context propagation.
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

    # Attach contextual metadata
    result.setdefault("context", {})
    result["context"].update(
        {
            "org_id": resolved_org_id,
            "campaign_id": campaign_id,
            "sender_id": sender_id,
            "metadata": metadata or {},
        }
    )

    return result
