# app/web/email_webhook.py
from fastapi import APIRouter, Request, HTTPException, Header
from datetime import datetime, timezone
import hmac, hashlib, logging, os

from app.web.schemas import WebhookEvent

router = APIRouter()
logger = logging.getLogger("cory.email_webhook")

# Use same secret pattern as SMS
EMAIL_WEBHOOK_SECRET = os.getenv("EMAIL_WEBHOOK_SECRET", "dev-secret")

def verify_hmac_signature(body_bytes: bytes, signature: str) -> bool:
    mac = hmac.new(EMAIL_WEBHOOK_SECRET.encode(), body_bytes, hashlib.sha256)
    expected = mac.hexdigest()
    return hmac.compare_digest(expected, signature)

@router.post("/webhooks/email")
async def email_webhook(request: Request, x_signature: str = Header(None)):
    # Read raw body for HMAC verification
    body_bytes = await request.body()
    if not x_signature or not verify_hmac_signature(body_bytes, x_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse JSON payload
    payload = await request.json()
    provider_ref = (
        payload.get("provider_ref")
        or payload.get("message_id")
        or payload.get("email_id")
    )

    if not provider_ref:
        raise HTTPException(status_code=422, detail="Missing provider_ref")

    # Check idempotency cache
    if not await request.app.state.idempotency.reserve(provider_ref):
        logger.info("Duplicate email webhook ignored", extra={"provider_ref": provider_ref})
        return {"status": "duplicate", "provider_ref": provider_ref, "data": payload}

    # Normalize into canonical WebhookEvent
    event = WebhookEvent(
        event="email_incoming",
        channel="email",
        timestamp=datetime.now(timezone.utc),
        payload=payload,
        metadata={"provider_ref": provider_ref}
    )

    await request.app.state.process_event_fn("email", event)

    return {"status": "received", "provider_ref": provider_ref, "data": payload}
