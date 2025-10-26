# app/web/sms_webhook.py
from fastapi import APIRouter, Request, HTTPException, Header
from datetime import datetime, timezone
import hmac, hashlib, logging, os, json

from app.web.schemas import WebhookEvent
from app.orchestrator.temporal.signal_bridge import signal_workflow

router = APIRouter()
logger = logging.getLogger("cory.sms_webhook")

# Load from environment
SMS_WEBHOOK_SECRET = os.getenv("SMS_WEBHOOK_SECRET", "super-secret-hmac-key")
DEFAULT_WORKFLOW_ID = os.getenv(
    "SMS_SIGNAL_WORKFLOW_ID", "answer-builder-00000000-0000-0000-0000-000000000042"
)

# --------------------------------------------------------------------------
# 🔐 Verify HMAC Signature
# --------------------------------------------------------------------------

def verify_hmac_signature(body_bytes: bytes, signature: str) -> bool:
    mac = hmac.new(SMS_WEBHOOK_SECRET.encode(), body_bytes, hashlib.sha256)
    expected = mac.hexdigest()
    return hmac.compare_digest(expected, signature)


# --------------------------------------------------------------------------
# 📩 Webhook Endpoint
# --------------------------------------------------------------------------

@router.post("/webhooks/sms")
async def sms_webhook(
    request: Request,
    x_signature: str = Header(None),
    x_hub_signature_256: str = Header(None),  # Alternate name used by some providers
):
    body_bytes = await request.body()

    # Validate signature
    signature = x_signature or x_hub_signature_256
    if not signature or not verify_hmac_signature(body_bytes, signature):
        raise HTTPException(status_code=401, detail="Invalid or missing signature")

    # Parse payload
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Malformed JSON payload")

    provider_ref = payload.get("message_id") or payload.get("sid")
    if not provider_ref:
        raise HTTPException(status_code=422, detail="Missing provider_ref")

    # Idempotency guard
    should_process = await request.app.state.idempotency.reserve(provider_ref)
    if not should_process:
        logger.info("Duplicate SMS webhook", extra={"provider_ref": provider_ref})
        return {"status": "duplicate", "provider_ref": provider_ref}

    # Normalize payload into canonical event
    event = WebhookEvent(
        event="sms_incoming",
        channel="sms",
        timestamp=datetime.now(timezone.utc),
        payload=payload,
        metadata={"provider_ref": provider_ref},
    )

    # ----------------------------------------------------------------------
    # 🔔 Bridge inbound SMS to Temporal workflow
    # ----------------------------------------------------------------------
    from_number = payload.get("from") or payload.get("From")
    body = payload.get("body") or payload.get("Body", "")

    try:
        await signal_workflow(
            signal_name="sms_inbound_signal",
            payload={"from": from_number, "body": body},
            workflow_id=DEFAULT_WORKFLOW_ID,
        )
        logger.info(
            "📨 Signal sent to Temporal workflow",
            extra={"from": from_number, "provider_ref": provider_ref},
        )
    except Exception as e:
        logger.warning(
            "⚠️ Failed to signal Temporal",
            extra={"error": str(e), "from": from_number, "provider_ref": provider_ref},
        )

    # ----------------------------------------------------------------------
    # Continue standard processing pipeline
    # ----------------------------------------------------------------------
    await request.app.state.process_event_fn("sms", event)

    logger.info(
        f"✅ Inbound SMS processed from {from_number}: {body[:80]}",
        extra={"provider_ref": provider_ref},
    )

    return {"status": "received", "provider_ref": provider_ref}
