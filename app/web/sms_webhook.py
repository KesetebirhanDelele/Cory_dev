# app/web/sms_webhook.py

import asyncio
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
from app.orchestrator.temporal.workflows.sms_direct_reply import SMSDirectReplyWorkflow

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

# In-process idempotency set (per web worker)
SEEN_PROVIDER_REFS: set[str] = set()


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
    try:
        supabase.table("contact").update(
            {
                "consent": enabled,
                "last_interaction_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("phone", phone).execute()
    except Exception as e:
        logger.exception("Failed to update contact.consent: %s", e)


def update_last_interaction(phone: str):
    """Uses correct DB column: contact.last_interaction_at"""
    if supabase is None or not phone:
        return
    try:
        supabase.table("contact").update(
            {"last_interaction_at": datetime.now(timezone.utc).isoformat()}
        ).eq("phone", phone).execute()
    except Exception as e:
        logger.exception("Failed to update last_interaction_at: %s", e)


# --------------------------------------------------------------------------
# 📥 LOG INBOUND MESSAGE → message TABLE
# --------------------------------------------------------------------------
def log_inbound_message(phone: str, body: str, provider_ref: str):
    """
    Persist inbound SMS into public.message.
    """
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
# 🔐 Verify HMAC Signature  (for non-Twilio / internal use)
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

    This does NOT send SMS. It only updates legacy CRM metadata.
    """
    if not inbound_text or not from_number or supabase is None:
        return None

    try:
        agent = ConversationalResponseAgent()
        classification = await agent.classify_message(inbound_text, channel="sms")

        intent = classification.get("intent")
        next_action = classification.get("next_action")

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

        # Update step
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
# 📩 SMS Webhook Endpoint  (DEBUG-FOCUSED, TWILIO-FRIENDLY)
# --------------------------------------------------------------------------
@router.post("/webhooks/sms")
async def sms_webhook(
    request: Request,
    x_signature: str = Header(None),
    x_timestamp: str = Header(None),
    x_nonce: str = Header(None),
    x_hub_signature_256: str = Header(None),
):
    """
    Primary inbound SMS entrypoint (debug-friendly).

    Key points:
      * Logs raw body + headers so you can see exactly what Twilio sent.
      * Never raises unhandled exceptions → Twilio should NOT see 500 anymore.
      * Still logs to DB and handles STOP/START/HELP.
      * Temporal / RAG handoff is wrapped in try/except so failures are visible
        in logs but do not break the webhook.
    """
    try:
        # ---------- 0. RAW DEBUG LOGGING ----------
        body_bytes = await request.body()
        raw_body = body_bytes.decode(errors="ignore")
        logger.info("💬 [SMS_WEBHOOK] raw body: %s", raw_body)
        logger.info("💬 [SMS_WEBHOOK] headers: %s", dict(request.headers))

        ENV = os.getenv("ENV", "local")

        # ---------- 1. HMAC VALIDATION (NON-FATAL) ----------
        try:
            if ENV == "production":
                # In production we assume Twilio + its own signature mechanism
                logger.info(
                    "[SMS_WEBHOOK] Production mode: skipping custom HMAC validation "
                    "(Twilio payload assumed)."
                )
            else:
                signature = x_signature or x_hub_signature_256
                if not (signature and x_timestamp and x_nonce):
                    logger.info(
                        "[SMS_WEBHOOK] Dev mode: missing HMAC headers, skipping validation."
                    )
                else:
                    ok = verify_hmac_signature(
                        body_bytes, signature, x_timestamp, x_nonce
                    )
                    if not ok:
                        logger.warning(
                            "[SMS_WEBHOOK] HMAC validation FAILED; continuing anyway "
                            "for debugging."
                        )
        except Exception as e:
            logger.exception(
                "[SMS_WEBHOOK] Unexpected error in HMAC block",
                extra={"error": str(e)},
            )

        # ---------- 2. PARSE FORM (Twilio sends x-www-form-urlencoded) ----------
        try:
            form = await request.form()
            payload = dict(form)
        except Exception as e:
            logger.exception(
                "[SMS_WEBHOOK] Failed to parse form data", extra={"error": str(e)}
            )
            return {
                "status": "error",
                "reason": "failed_to_parse_form",
            }

        logger.info("💬 [SMS_WEBHOOK] parsed payload: %s", payload)

        # ---------- 3. BASIC FIELDS ----------
        # Twilio gives us MessageSid / SmsMessageSid; use that as provider_ref
        provider_ref = (
            payload.get("MessageSid")
            or payload.get("SmsSid")
            or payload.get("SmsMessageSid")
            or payload.get("sid")
        )

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

        if not provider_ref:
            logger.error(
                "[SMS_WEBHOOK] Missing provider_ref (MessageSid/SmsSid)",
                extra={"payload": payload},
            )
            return {
                "status": "error",
                "reason": "missing_provider_ref",
                "payload": payload,
            }

        if not from_number:
            logger.error(
                "[SMS_WEBHOOK] Missing from_number",
                extra={"payload": payload},
            )
            return {
                "status": "error",
                "reason": "missing_from_number",
                "provider_ref": provider_ref,
                "payload": payload,
            }

        try:
            normalized_from = normalize_phone(from_number)
        except Exception as e:
            logger.exception(
                "[SMS_WEBHOOK] normalize_phone failed, falling back to raw number",
                extra={"error": str(e), "from_number": from_number},
            )
            normalized_from = from_number

        logger.info(
            "💬 [SMS_WEBHOOK] inbound SMS | from=%s | provider_ref=%s | text=%r",
            normalized_from,
            provider_ref,
            inbound_text,
        )

        # ---------- 3b. IDEMPOTENCY (in-process + optional cache) ----------
        is_duplicate = False
        try:
            global SEEN_PROVIDER_REFS
            if provider_ref in SEEN_PROVIDER_REFS:
                is_duplicate = True
            else:
                SEEN_PROVIDER_REFS.add(provider_ref)

            # Best-effort use of shared IdempotencyCache if present,
            # without assuming any particular API except .set(...)
            cache = getattr(request.app.state, "processed_refs", None)
            if cache is not None and hasattr(cache, "set"):
                try:
                    cache.set(provider_ref, True)
                except Exception as e:
                    logger.warning(
                        "[SMS_WEBHOOK] Idempotency cache error (non-fatal)",
                        extra={"error": str(e)},
                    )
        except Exception as e:
            logger.warning(
                "[SMS_WEBHOOK] Idempotency dedupe error (non-fatal)",
                extra={"error": str(e)},
            )

        if is_duplicate:
            logger.info(
                "[SMS_WEBHOOK] Duplicate inbound SMS, acknowledging without reprocessing",
                extra={"provider_ref": provider_ref},
            )
            return {
                "status": "duplicate",
                "provider_ref": provider_ref,
                "from": normalized_from,
            }

        # ---------- 4. COMPLIANCE / STOP / START / HELP ----------
        try:
            compliance = compliance_keyword(inbound_text or "")
        except Exception as e:
            logger.exception(
                "[SMS_WEBHOOK] compliance_keyword failed", extra={"error": str(e)}
            )
            compliance = None

        try:
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
        except Exception as e:
            logger.exception(
                "[SMS_WEBHOOK] compliance handling failed", extra={"error": str(e)}
            )
            # Fall through to normal processing

        # ---------- 5. NORMAL INBOUND LOGGING ----------
        try:
            log_inbound_message(normalized_from, inbound_text, provider_ref)
            update_last_interaction(normalized_from)
        except Exception as e:
            logger.exception(
                "[SMS_WEBHOOK] inbound logging failed", extra={"error": str(e)}
            )

        # ---------- 6. CLASSIFY (NON-FATAL) ----------
        try:
            await _classify_and_update_campaign_step(
                inbound_text=inbound_text,
                from_number=normalized_from,
            )
        except Exception as e:
            logger.exception(
                "[SMS_WEBHOOK] classification failed", extra={"error": str(e)}
            )

        # ---------- 7. TEMPORAL HANDOFF (NON-FATAL) ----------
        try:
            from temporalio.client import Client

            temporal_client: Client | None = getattr(
                request.app.state, "temporal_client", None
            )

            if temporal_client is None:
                logger.warning(
                    "[SMS_WEBHOOK] No Temporal client available; skipping workflow start"
                )
            else:
                logger.info(
                    "📨 [SMS_WEBHOOK] Starting SMSDirectReplyWorkflow | to=%s provider_ref=%s",
                    normalized_from,
                    provider_ref,
                )

                await temporal_client.start_workflow(
                    SMSDirectReplyWorkflow.run,
                    {
                        "to": normalized_from,
                        "body": inbound_text,
                    },  # 👈 matches workflow.run(self, payload: dict)
                    id=f"sms-auto-reply-{provider_ref}",
                    task_queue=os.getenv(
                        "TEMPORAL_COMM_TASK_QUEUE", "cory-handoff-queue"
                    ),
                )
        except Exception as e:
            logger.exception(
                "[SMS_WEBHOOK] Temporal handoff failed", extra={"error": str(e)}
            )

        # ---------- 8. FINAL RESPONSE ----------
        return {
            "status": "received",
            "provider_ref": provider_ref,
            "from": normalized_from,
            "to": payload.get("To"),
            "body": inbound_text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        # Last-resort safety net: never 500 to Twilio
        logger.exception("[SMS_WEBHOOK] Unhandled exception", extra={"error": str(e)})
        return {
            "status": "error",
            "reason": "unhandled_exception",
            "message": str(e),
        }
