# app/web/sms_webhook.py

from fastapi import APIRouter, Request, HTTPException, Header
from datetime import datetime, timezone
import hmac
import hashlib
import logging
import os
import phonenumbers

from supabase import create_client, Client

from app.web.schemas import WebhookEvent  # kept in case other code imports it
from app.agents.conversational_response_agent import ConversationalResponseAgent
from app.channels.sms_query_handler import handle_inbound_sms

router = APIRouter()
logger = logging.getLogger("cory.sms_webhook")

# --------------------------------------------------------------------------
# 🔑 Environment / configuration
# --------------------------------------------------------------------------
SMS_WEBHOOK_SECRET = os.getenv("SMS_WEBHOOK_SECRET", "super-secret-hmac-key")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

supabase: Client | None = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    logger.warning("Supabase credentials missing — inbound SMS DB logging disabled.")


# --------------------------------------------------------------------------
# 📞 Phone normalization
# --------------------------------------------------------------------------
def normalize_phone(num: str | None) -> str | None:
    if not num:
        return None
    try:
        parsed = phonenumbers.parse(num, "US")
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        return num


# --------------------------------------------------------------------------
# 🛑 STOP / START / HELP compliance
# --------------------------------------------------------------------------
def compliance_keyword(text: str) -> str | None:
    txt = text.strip().lower()
    if txt in {"stop", "unsubscribe", "quit"}:
        return "stop"
    if txt in {"start", "unstop"}:
        return "start"
    if txt == "help":
        return "help"
    return None


def set_sms_opt_in(phone: str, enabled: bool):
    """Uses correct DB column: contact.consent"""
    if supabase is None or not phone:
        return
    supabase.table("contact").update(
        {
            "consent": enabled,
            "last_interaction_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("phone", phone).execute()


def update_last_interaction(phone: str):
    """Uses correct DB column: contact.last_interaction_at"""
    if supabase is None or not phone:
        return
    supabase.table("contact").update(
        {"last_interaction_at": datetime.now(timezone.utc).isoformat()}
    ).eq("phone", phone).execute()


# --------------------------------------------------------------------------
# 📥 LOG INBOUND MESSAGE → message TABLE
# --------------------------------------------------------------------------
def log_inbound_message(phone: str, body: str, provider_ref: str):
    # If Supabase is not configured, skip safely
    global supabase
    if supabase is None:
        logger.warning("Supabase not configured — skipping inbound message logging")
        return

    try:
        project_id = None
        enrollment_id = None

        # Lookup contact
        contact_res = (
            supabase.table("contact")
            .select("id, project_id")
            .eq("phone", phone)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

        if contact_res.data:
            contact = contact_res.data[0]
            project_id = contact.get("project_id")

            # Lookup latest enrollment
            enr_res = (
                supabase.table("enrollment")
                .select("id")
                .eq("contact_id", contact["id"])
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )

            if enr_res.data:
                enrollment_id = enr_res.data[0]["id"]

        supabase.table("message").insert(
            {
                "project_id": project_id,
                "enrollment_id": enrollment_id,
                "channel": "sms",
                "direction": "inbound",
                "content": {"text": body},
                "provider_ref": provider_ref,
                "status": "received",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()

    except Exception as e:
        logger.exception("Failed inbound logging → skipping: %s", e)


# --------------------------------------------------------------------------
# 🔐 Verify HMAC Signature
# --------------------------------------------------------------------------
def verify_hmac_signature(body_bytes: bytes, signature: str, timestamp: str, nonce: str) -> bool:
    raw_body = body_bytes.decode()
    message = f"{timestamp}.{nonce}.{raw_body}".encode()
    mac = hmac.new(SMS_WEBHOOK_SECRET.encode(), message, hashlib.sha256)
    return hmac.compare_digest(mac.hexdigest(), signature)


# --------------------------------------------------------------------------
# 🧠 Classification + campaign step updater (no direct SMS send)
# --------------------------------------------------------------------------
async def _classify_and_update_campaign_step(
    *, inbound_text: str, from_number: str | None
):
    """
    Use ConversationalResponseAgent to classify for CRM/campaign updates.
    Does NOT send SMS; AnswerWorkflow handles replies.
    """
    if not inbound_text or not from_number or supabase is None:
        return None

    try:
        agent = ConversationalResponseAgent()
        classification = await agent.classify_message(inbound_text, channel="sms")

        intent = classification.get("intent")
        next_action = classification.get("next_action")

        # No intent → nothing to update
        if not intent:
            return classification

        # Lookup contact
        contact_res = (
            supabase.table("contact")
            .select("id")
            .eq("phone", from_number)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not contact_res.data:
            return classification

        contact_id = contact_res.data[0]["id"]

        # Latest enrollment
        enr_res = (
            supabase.table("enrollment")
            .select("registration_id")
            .eq("contact_id", contact_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not enr_res.data:
            return classification

        registration_id = enr_res.data[0]["registration_id"]

        # Latest step
        step_res = (
            supabase.table("lead_campaign_steps")
            .select("id")
            .eq("registration_id", registration_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not step_res.data:
            return classification

        step_id = step_res.data[0]["id"]

        # Update step using only columns that exist
        supabase.table("lead_campaign_steps").update(
            {
                "status": "completed",
                "metadata": {"intent": intent, "next_action": next_action},
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", step_id).execute()

        return classification

    except Exception as e:
        logger.exception("Failed to classify inbound SMS: %s", e)
        return None


# --------------------------------------------------------------------------
# 📩 SMS Webhook Endpoint
# --------------------------------------------------------------------------
@router.post("/webhooks/sms")
async def sms_webhook(
    request: Request,
    x_signature: str = Header(None),
    x_timestamp: str = Header(None),
    x_nonce: str = Header(None),
    x_hub_signature_256: str = Header(None),
):
    body_bytes = await request.body()
    print("SERVER RECEIVED BODY:", body_bytes.decode())

    ENV = os.getenv("ENV", "local")

    # Twilio does NOT send our custom HMAC headers → allow through
    if ENV == "production":
        print("[INFO] Production mode — skipping custom HMAC for Twilio SMS")
    else:
        # In local/dev environments still enforce HMAC if present
        signature = x_signature or x_hub_signature_256
        if not (signature and x_timestamp and x_nonce):
            print("[DEV] Missing HMAC headers — skipping validation")
        else:
            if not verify_hmac_signature(body_bytes, signature, x_timestamp, x_nonce):
                raise HTTPException(401, "Invalid signature")

    form = await request.form()
    payload = dict(form)

    provider_ref = (
        payload.get("MessageSid")
        or payload.get("SmsSid")
        or payload.get("SmsMessageSid")
        or payload.get("sid")
    )

    if not provider_ref:
        raise HTTPException(422, f"Missing provider_ref in payload: {payload}")

    from_number = (
        payload.get("fromNumber")
        or payload.get("from")
        or payload.get("From")
    )
    inbound_text = (
        payload.get("message")
        or payload.get("body")
        or payload.get("Body")
        or ""
    )

    normalized_from = normalize_phone(from_number)

    # ----------------
    # Compliance / STOP
    # ----------------
    compliance = compliance_keyword(inbound_text)
    if compliance == "stop":
        set_sms_opt_in(normalized_from, False)
        log_inbound_message(normalized_from, inbound_text, provider_ref)
        update_last_interaction(normalized_from)
        return {"status": "STOP applied"}

    if compliance == "start":
        set_sms_opt_in(normalized_from, True)
        log_inbound_message(normalized_from, inbound_text, provider_ref)
        update_last_interaction(normalized_from)
        return {"status": "START applied"}

    if compliance == "help":
        log_inbound_message(normalized_from, inbound_text, provider_ref)
        update_last_interaction(normalized_from)
        return {"status": "HELP acknowledged"}

    # Log normal inbound
    log_inbound_message(normalized_from, inbound_text, provider_ref)
    update_last_interaction(normalized_from)

    # -------------------------------------------------
    # 1) Classify for CRM / campaign updates (no SMS here)
    # -------------------------------------------------
    await _classify_and_update_campaign_step(
        inbound_text=inbound_text,
        from_number=normalized_from,
    )

    # -------------------------------------------------
    # 2) Idempotency check before RAG processing
    # -------------------------------------------------
    should_process = await request.app.state.idempotency.reserve(provider_ref)
    if not should_process:
        return {"status": "duplicate", "provider_ref": provider_ref}

    # -------------------------------------------------
    # 3) Hand off to Temporal AnswerWorkflow (RAG + SMS reply)
    # -------------------------------------------------
    from temporalio.client import Client

    temporal_client: Client = request.app.state.temporal_client

    await handle_inbound_sms(
        client=temporal_client,
        from_number=normalized_from,
        body=inbound_text,
        provider_ref=provider_ref,
        threshold=0.5,
    )

    return {"status": "received", "provider_ref": provider_ref}
