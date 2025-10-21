# app/web/wa_webhook.py
from fastapi import APIRouter, Request, HTTPException, Header
from datetime import datetime, timezone
import hmac, hashlib, logging, os

from app.web.schemas import WebhookEvent

router = APIRouter()
logger = logging.getLogger("cory.wa_webhook")

WA_WEBHOOK_SECRET = os.getenv("WA_WEBHOOK_SECRET", "dev-secret")

def verify_hmac_signature(body_bytes: bytes, signature: str) -> bool:
    mac = hmac.new(WA_WEBHOOK_SECRET.encode(), body_bytes, hashlib.sha256)
    expected = mac.hexdigest()
    return hmac.compare_digest(expected, signature)

@router.post("/webhooks/wa")
async def wa_webhook(request: Request, x_signature: str = Header(None)):
    # Step 1 — Verify signature
    body_bytes = await request.body()
    if not x_signature or not verify_hmac_signature(body_bytes, x_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Step 2 — Parse payload
    payload = await request.json()
    provider_ref = (
        payload.get("provider_ref")
        or payload.get("message_id")
        or payload.get("wa_id")
    )

    if not provider_ref:
        raise HTTPException(status_code=422, detail="Missing provider_ref")

    # Step 3 — Idempotency check
    if not await request.app.state.idempotency.reserve(provider_ref):
        logger.info("Duplicate WhatsApp webhook ignored", extra={"provider_ref": provider_ref})
        return {"status": "duplicate", "provider_ref": provider_ref, "data": payload}

    # Step 4 — Normalize event into canonical model
    event = WebhookEvent(
        event="wa_incoming",
        channel="whatsapp",
        timestamp=datetime.now(timezone.utc),
        payload=payload,
        metadata={"provider_ref": provider_ref}
    )

    # Step 5 — Pass to processing function (same test hook)
    await request.app.state.process_event_fn("whatsapp", event)

    return {"status": "received", "provider_ref": provider_ref, "data": payload}
