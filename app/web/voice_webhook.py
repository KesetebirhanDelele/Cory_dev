# app/web/voice_webhook.py
from fastapi import APIRouter, Request, HTTPException, Header
from datetime import datetime, timezone
import hmac, hashlib, logging, os

from app.web.schemas import WebhookEvent

router = APIRouter()
logger = logging.getLogger("cory.voice_webhook")

VOICE_WEBHOOK_SECRET = os.getenv("VOICE_WEBHOOK_SECRET", "dev-secret")

def verify_hmac_signature(body_bytes: bytes, signature: str) -> bool:
    mac = hmac.new(VOICE_WEBHOOK_SECRET.encode(), body_bytes, hashlib.sha256)
    expected = mac.hexdigest()
    return hmac.compare_digest(expected, signature)

@router.post("/webhooks/voice")
async def voice_webhook(request: Request, x_signature: str = Header(None)):
    # Read raw body for signature verification
    body_bytes = await request.body()
    if not x_signature or not verify_hmac_signature(body_bytes, x_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse payload
    payload = await request.json()
    provider_ref = (
        payload.get("provider_ref")
        or payload.get("call_id")
        or payload.get("sid")
    )

    if not provider_ref:
        raise HTTPException(status_code=422, detail="Missing provider_ref")

    # Idempotency check
    if not await request.app.state.idempotency.reserve(provider_ref):
        logger.info("Duplicate voice webhook ignored", extra={"provider_ref": provider_ref})
        return {"status": "duplicate", "provider_ref": provider_ref, "data": payload}

    # Normalize into canonical model
    event = WebhookEvent(
        event="voice_incoming",
        channel="voice",
        timestamp=datetime.now(timezone.utc),
        payload=payload,
        metadata={"provider_ref": provider_ref},
    )

    await request.app.state.process_event_fn("voice", event)

    return {"status": "received", "provider_ref": provider_ref, "data": payload}
