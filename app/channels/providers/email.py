# app/channels/providers/email.py
import os
import uuid
import httpx
import logging

logger = logging.getLogger("cory.email")

async def send_email(org_id: str, enrollment_id: str, subject: str, body: str, *, to: str) -> dict:
    """Send email via Mandrill (or mock in stub mode)."""
    live_mode = os.getenv("CORY_LIVE_CHANNELS", "0") == "1"

    if not live_mode:
        return {
            "channel": "email",
            "enrollment_id": enrollment_id,
            "provider_ref": f"mock-email-{uuid.uuid4().hex[:8]}",
            "status": "queued",
            "request": {"to": to, "subject": subject, "body": body},
        }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://mandrillapp.com/api/1.0/messages/send.json",
                json={
                    "key": os.getenv("MANDRILL_API_KEY", "test-key"),
                    "message": {
                        "from_email": "noreply@example.com",
                        "to": [{"email": to, "type": "to"}],
                        "subject": subject,
                        "text": body,
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()
            msg_id = data[0]["_id"] if isinstance(data, list) and data else uuid.uuid4().hex[:8]
            return {
                "channel": "email",
                "enrollment_id": enrollment_id,
                "provider_ref": msg_id,
                "status": "sent",
                "request": {"to": to, "subject": subject, "body": body},
            }
    except httpx.HTTPStatusError as e:
        logger.warning(f"Email send failed with {e.response.status_code}: {e}")
        status_map = {
            429: "RATE_LIMIT",
            500: "TEMPORARY_FAILURE",
            400: "PERMANENT_FAILURE",
        }
        mapped = status_map.get(e.response.status_code, "TEMPORARY_FAILURE")
        return {
            "channel": "email",
            "enrollment_id": enrollment_id,
            "provider_ref": None,
            "status": mapped,
            "request": {"to": to, "subject": subject, "body": body},
        }
    except Exception as e:
        logger.error(f"Unexpected error sending email: {e}")
        return {
            "channel": "email",
            "enrollment_id": enrollment_id,
            "provider_ref": None,
            "status": "TEMPORARY_FAILURE",
            "request": {"to": to, "subject": subject, "body": body},
        }

