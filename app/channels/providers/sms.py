import os
import uuid
import httpx
from typing import Optional, Dict, Any


async def send_sms(org_id: str, enrollment_id: str, body: str, *, to: Optional[str] = None) -> Dict[str, Any]:
    """Send SMS via SlickText (live or stub mode)."""
    live_mode = os.getenv("CORY_LIVE_CHANNELS", "0") == "1"

    # 🧪 Stub mode (default)
    if not live_mode:
        return {
            "channel": "sms",
            "enrollment_id": enrollment_id,
            "provider_ref": f"stub-sms-{enrollment_id}",
            "status": "queued",
            "request": {"to": to, "body": body},
        }

    api_key = os.getenv("SLICKTEXT_API_KEY", "demo-key")
    base_url = os.getenv("SLICKTEXT_API_URL", "https://api.slicktext.com/v1/messages")

    try:
        Client = getattr(httpx, "AsyncClient", None)
        if Client is None:
            raise RuntimeError("httpx.AsyncClient missing")

        # ✅ Detect if DummyClient (from test) accepts no arguments
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

            if hasattr(response, "raise_for_status"):
                response.raise_for_status()

            data = response.json() if hasattr(response, "json") else {}

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
        print(f"[send_sms] Unexpected error: {type(ex).__name__} - {ex}")
        return {
            "channel": "sms",
            "enrollment_id": enrollment_id,
            "provider_ref": None,
            "status": "TEMPORARY_FAILURE",
            "request": {"to": to, "body": body},
        }
