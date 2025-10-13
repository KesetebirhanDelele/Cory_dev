from temporalio import activity
from typing import Dict, Any
import logging

from app.channels.providers import sms as sms_client
from app.data import supabase_repo as repo
from app.policy.guards import evaluate_policy_guards
from app.policy.guards_budget import evaluate_budget_caps
from app.data.telemetry import log_decision_to_audit  # optional audit hook
from app.data.db import supabase  # preferred asyncpg accessor

logger = logging.getLogger(__name__)


@activity.defn(name="sms_send")
async def sms_send(enrollment_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send an SMS message through the configured provider,
    enforcing quiet hours, consent, frequency, and budget/rate caps.

    payload example:
    {
        "lead": {...},
        "organization": {...},
        "to": "+15551234567",
        "body": "Hi there!",
        "idempotency_key": "optional-key",
        "campaign_id": "CAMP123"
    }
    """
    channel = "sms"
    lead = payload.get("lead", {})
    org = payload.get("organization", {})
    campaign_id = payload.get("campaign_id")

    # --- Acquire DB connection or pool -------------------------------------
    db = supabase

    # --- Policy Guard Check (C2.1) -----------------------------------------
    allowed, reason = await evaluate_policy_guards(db, lead, org, channel)
    if not allowed:
        logger.info(
            "SendBlockedPolicy",
            extra={
                "enrollment_id": enrollment_id,
                "lead_id": lead.get("id"),
                "channel": channel,
                "reason": reason,
            },
        )
        await log_decision_to_audit(lead.get("id"), channel, reason)
        return {
            "channel": channel,
            "enrollment_id": enrollment_id,
            "status": "blocked",
            "reason": reason,
            "stage": "policy_guard",
            "request": payload,
        }

    # --- Budget / Rate Cap Check (C2.2) ------------------------------------
    allowed, reason, hint = await evaluate_budget_caps(
        db=db,
        campaign_id=campaign_id,
        channel=channel,
        policy=org.get("policy", {}),
    )
    if not allowed:
        logger.info(
            "SendBlockedBudget",
            extra={
                "enrollment_id": enrollment_id,
                "campaign_id": campaign_id,
                "channel": channel,
                "reason": reason,
                "hint": hint,
            },
        )
        await log_decision_to_audit(lead.get("id"), channel, reason)
        return {
            "channel": channel,
            "enrollment_id": enrollment_id,
            "campaign_id": campaign_id,
            "status": "blocked",
            "reason": reason,
            "hint": hint,
            "stage": "budget_guard",
            "request": payload,
        }

    # --- Provider Send ------------------------------------------------------
    try:
        ref = await sms_client.send(
            to=payload["to"],
            body=payload["body"],
            idempotency_key=payload.get("idempotency_key"),
        )

        # Optional: log outbound message
        try:
            await repo.log_outbound(
                enrollment_id=enrollment_id,
                channel=channel,
                provider_ref=ref,
            )
        except Exception as log_ex:
            logger.warning("OutboundLogFailed", extra={"error": str(log_ex)})

        logger.info(
            "SMSDispatched",
            extra={
                "enrollment_id": enrollment_id,
                "lead_id": lead.get("id"),
                "provider_ref": ref,
                "status": "sent",
            },
        )
        return {
            "channel": channel,
            "enrollment_id": enrollment_id,
            "provider_ref": ref,
            "status": "sent",
            "request": payload,
        }

    except Exception as e:
        logger.error(
            "SMSError",
            extra={
                "enrollment_id": enrollment_id,
                "lead_id": lead.get("id"),
                "error": str(e),
            },
            exc_info=True,
        )
        return {
            "channel": channel,
            "enrollment_id": enrollment_id,
            "status": "failed",
            "error": str(e),
            "request": payload,
        }
