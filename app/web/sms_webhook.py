# app/web/sms_webhook.py
from fastapi import APIRouter, Request, HTTPException, Header
import hmac, hashlib, logging
from app.web.schemas import WebhookEvent
from datetime import datetime, timezone

router = APIRouter()
logger = logging.getLogger("cory.sms_webhook")

# Example: secret shared with SMS provider (load from env)
SMS_WEBHOOK_SECRET = "super-secret-hmac-key"

def verify_hmac_signature(body_bytes: bytes, signature: str) -> bool:
    mac = hmac.new(SMS_WEBHOOK_SECRET.encode(), body_bytes, hashlib.sha256)
    expected = mac.hexdigest()
    return hmac.compare_digest(expected, signature)

@router.post("/webhooks/sms")
async def sms_webhook(request: Request, x_signature: str = Header(None)):
    body_bytes = await request.body()
    if not x_signature or not verify_hmac_signature(body_bytes, x_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()

    provider_ref = payload.get("message_id") or payload.get("sid")
    if not provider_ref:
        raise HTTPException(status_code=422, detail="Missing provider_ref")

    # Idempotency guard
    if provider_ref:
        should_process = await request.app.state.idempotency.reserve(provider_ref)
        if not should_process:
            logger.info("duplicate SMS webhook", extra={"provider_ref": provider_ref})
            return {"status": "duplicate", "provider_ref": provider_ref}

    # Normalize payload into canonical shape
    event = WebhookEvent(
        event="sms_incoming",
        channel="sms",
        timestamp=datetime.now(timezone.utc),
        payload=payload,
        metadata={"provider_ref": provider_ref}
    )

    await request.app.state.process_event_fn("sms", event)

    return {"status": "received", "provider_ref": provider_ref}
