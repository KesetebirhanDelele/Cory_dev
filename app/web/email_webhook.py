# app/web/email_webhook.py

from fastapi import APIRouter, Request, HTTPException, Header
from datetime import datetime, timezone
import hmac
import hashlib
import logging
import os

from supabase import create_client, Client

from app.web.schemas import WebhookEvent
from app.agents.conversational_response_agent import ConversationalResponseAgent

router = APIRouter()
logger = logging.getLogger("cory.email_webhook")

# --------------------------------------------------------------------------
# 🔐 Secret & Supabase setup
# --------------------------------------------------------------------------
EMAIL_WEBHOOK_SECRET = os.getenv("EMAIL_WEBHOOK_SECRET", "dev-secret")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
supabase: Client | None = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    logger.warning(
        "Supabase credentials not set; email intent classification → lead_campaign_steps will be disabled."
    )


def verify_hmac_signature(body_bytes: bytes, signature: str) -> bool:
    mac = hmac.new(EMAIL_WEBHOOK_SECRET.encode(), body_bytes, hashlib.sha256)
    expected = mac.hexdigest()
    return hmac.compare_digest(expected, signature)


# --------------------------------------------------------------------------
# 🧠 Helper: classify email + update lead_campaign_steps
# --------------------------------------------------------------------------
async def _classify_and_update_campaign_step_email(
    *,
    inbound_text: str,
    from_email: str | None,
) -> dict | None:
    """
    Use ConversationalResponseAgent to classify an inbound Email and stamp
    intent + next_action onto the latest lead_campaign_steps row for the
    associated enrollment (resolved via contact.email).

    Returns the classification dict, or None if classification wasn't possible.
    """
    if not inbound_text or not from_email:
        return None
    if supabase is None:
        # No DB access configured; nothing we can do here
        return None

    try:
        # 1️⃣ Classify the inbound text
        agent = ConversationalResponseAgent()
        classification = await agent.classify_message(inbound_text, channel="email")

        intent = classification.get("intent")
        next_action = classification.get("next_action")
        if not intent:
            return classification

        # 2️⃣ Resolve contact by email
        contact_res = (
            supabase.table("contact")
            .select("id")
            .eq("email", from_email)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not contact_res.data:
            logger.info(
                "[email_webhook] No contact found for email %s; skipping campaign_step update",
                from_email,
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
                "[email_webhook] No enrollment found for contact %s; skipping campaign_step update",
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
                "[email_webhook] No lead_campaign_steps found for registration %s; skipping",
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
            "[email_webhook] Updated lead_campaign_steps | email=%s step_id=%s intent=%s next_action=%s",
            from_email,
            step_id,
            intent,
            next_action,
        )

        return classification

    except Exception as e:  # noqa: BLE001
        logger.exception(
            "Failed to classify inbound Email and update campaign step: %s", e
        )
        return None


# --------------------------------------------------------------------------
# 📩 Webhook Endpoint
# --------------------------------------------------------------------------
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

    # ----------------------------------------------------------------------
    # 🧠 Classify + update DB *before* building WebhookEvent
    # so intent can be carried into ProviderEvent → CampaignWorkflow
    # ----------------------------------------------------------------------
    from_email = (
        payload.get("from_email")
        or payload.get("from")
        or payload.get("sender")
    )
    inbound_text = (
        payload.get("text")
        or payload.get("plain_body")
        or payload.get("body")
        or ""
    )

    classification: dict | None = None
    try:
        classification = await _classify_and_update_campaign_step_email(
            inbound_text=inbound_text,
            from_email=from_email,
        )
    except Exception as e:  # extra safety
        logger.warning(
            "⚠️ Failed Email intent classification pipeline",
            extra={"error": str(e), "from_email": from_email, "provider_ref": provider_ref},
        )

    intent = (classification or {}).get("intent")
    next_action = (classification or {}).get("next_action")

    # Check idempotency cache
    if not await request.app.state.idempotency.reserve(provider_ref):
        logger.info(
            "Duplicate email webhook ignored", extra={"provider_ref": provider_ref}
        )
        return {"status": "duplicate", "provider_ref": provider_ref, "data": payload}

    # Normalize into canonical WebhookEvent
    event = WebhookEvent(
        event="email_incoming",
        channel="email",
        timestamp=datetime.now(timezone.utc),
        payload=payload,
        metadata={
            "provider_ref": provider_ref,
            # 🔥 make intent visible to ProviderEvent / CampaignWorkflow
            "intent": intent,
            "next_action": next_action,
            "from_email": from_email,
        },
    )

    # Continue existing processing pipeline
    await request.app.state.process_event_fn("email", event)

    return {
        "status": "received",
        "provider_ref": provider_ref,
        "intent": intent,
        "next_action": next_action,
        "data": payload,
    }
