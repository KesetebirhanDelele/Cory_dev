# app/web/sms_webhook.py

from fastapi import APIRouter, Request, HTTPException, Header
from datetime import datetime, timezone
import hmac
import hashlib
import logging
import os
import json

from supabase import create_client, Client

from app.web.schemas import WebhookEvent
from app.orchestrator.temporal.signal_bridge import signal_workflow
from app.agents.conversational_response_agent import ConversationalResponseAgent

router = APIRouter()
logger = logging.getLogger("cory.sms_webhook")

# --------------------------------------------------------------------------
# 🔑 Environment / configuration
# --------------------------------------------------------------------------
SMS_WEBHOOK_SECRET = os.getenv("SMS_WEBHOOK_SECRET", "super-secret-hmac-key")
DEFAULT_WORKFLOW_ID = os.getenv(
    "SMS_SIGNAL_WORKFLOW_ID",
    "answer-builder-00000000-0000-0000-0000-000000000042",
)

# Supabase client (used for intent → lead_campaign_steps updates)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
supabase: Client | None = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    logger.warning(
        "Supabase credentials not set; SMS intent classification → lead_campaign_steps will be disabled."
    )


# --------------------------------------------------------------------------
# 🔐 Verify HMAC Signature
# --------------------------------------------------------------------------
def verify_hmac_signature(body_bytes: bytes, signature: str) -> bool:
    mac = hmac.new(SMS_WEBHOOK_SECRET.encode(), body_bytes, hashlib.sha256)
    expected = mac.hexdigest()
    return hmac.compare_digest(expected, signature)


# --------------------------------------------------------------------------
# 🧠 Helper: classify SMS + update lead_campaign_steps
# --------------------------------------------------------------------------
async def _classify_and_update_campaign_step(
    *,
    inbound_text: str,
    from_number: str | None,
) -> dict | None:
    """
    Use ConversationalResponseAgent to classify an inbound SMS and stamp
    intent + next_action onto the latest lead_campaign_steps row for the
    associated enrollment (resolved via contact.phone).

    Returns the classification dict, or None if classification wasn't possible.
    """
    if not inbound_text or not from_number:
        return None
    if supabase is None:
        # No DB access configured; nothing we can do here
        return None

    try:
        # 1️⃣ Classify the inbound text
        agent = ConversationalResponseAgent()
        classification = await agent.classify_message(inbound_text, channel="sms")

        intent = classification.get("intent")
        next_action = classification.get("next_action")
        if not intent:
            return classification

        # 2️⃣ Resolve contact by phone number
        contact_res = (
            supabase.table("contact")
            .select("id")
            .eq("phone", from_number)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not contact_res.data:
            logger.info(
                "[sms_webhook] No contact found for phone %s; skipping campaign_step update",
                from_number,
            )
            return classification

        contact_id = contact_res.data[0]["id"]

        # 3️⃣ Get most recent enrollment for this contact
        enr_res = (
            supabase.table("enrollment")
            .select("id, registration_id")
            .eq("contact_id", contact_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not enr_res.data:
            logger.info(
                "[sms_webhook] No enrollment found for contact %s; skipping campaign_step update",
                contact_id,
            )
            return classification

        enrollment = enr_res.data[0]
        registration_id = enrollment["registration_id"]

        # 4️⃣ Find most recent campaign step for this registration
        step_res = (
            supabase.table("lead_campaign_steps")
            .select("id")
            .eq("registration_id", registration_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not step_res.data:
            logger.info(
                "[sms_webhook] No lead_campaign_steps found for registration %s; skipping",
                registration_id,
            )
            return classification

        step_id = step_res.data[0]["id"]

        # 5️⃣ Update intent + next_action on that step
        supabase.table("lead_campaign_steps").update(
            {
                "intent": intent,
                "next_action": next_action,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", step_id).execute()

        logger.info(
            "[sms_webhook] Updated lead_campaign_steps | phone=%s step_id=%s intent=%s next_action=%s",
            from_number,
            step_id,
            intent,
            next_action,
        )

        return classification

    except Exception as e:  # noqa: BLE001
        logger.exception(
            "Failed to classify inbound SMS and update campaign step: %s", e
        )
        return None


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

    from_number = payload.get("from") or payload.get("From")
    body = payload.get("body") or payload.get("Body", "") or ""

    # ----------------------------------------------------------------------
    # 🧠 Classify + update DB *before* building WebhookEvent
    # so intent can be carried into ProviderEvent → CampaignWorkflow
    # ----------------------------------------------------------------------
    classification: dict | None = None
    try:
        classification = await _classify_and_update_campaign_step(
            inbound_text=body,
            from_number=from_number,
        )
    except Exception as e:  # extra safety net
        logger.warning(
            "⚠️ Failed SMS intent classification pipeline",
            extra={"error": str(e), "from": from_number, "provider_ref": provider_ref},
        )

    intent = (classification or {}).get("intent")
    next_action = (classification or {}).get("next_action")

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
        metadata={
            "provider_ref": provider_ref,
            # 🔥 make intent visible to ProviderEvent / CampaignWorkflow
            "intent": intent,
            "next_action": next_action,
            "from": from_number,
        },
    )

    # ----------------------------------------------------------------------
    # 🔔 Bridge inbound SMS to Temporal workflow (answer-builder flow)
    # ----------------------------------------------------------------------
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
    # Continue standard processing pipeline (logs, ProviderEvent, etc.)
    # ----------------------------------------------------------------------
    await request.app.state.process_event_fn("sms", event)

    logger.info(
        "✅ Inbound SMS processed from %s: %s",
        from_number,
        body[:80],
        extra={"provider_ref": provider_ref, "intent": intent, "next_action": next_action},
    )

    return {"status": "received", "provider_ref": provider_ref}
