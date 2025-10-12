from temporalio import activity
from typing import Dict, Any
import logging

from app.channels.providers import sms as sms_client
from app.data import supabase_repo as repo
from app.policy.guards import evaluate_policy_guards
from app.data.db import get_db  # asyncpg pool accessor
from app.data.telemetry import log_decision_to_audit  # optional helper

logger = logging.getLogger(__name__)


@activity.defn(name="sms_send")
async def sms_send(enrollment_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send an SMS message through the configured provider,
    enforcing quiet hours, consent, and frequency caps before dispatch.

    payload example:
    {
        "lead": {...},
        "organization": {...},
        "to": "+15551234567",
        "body": "Hi there!",
        "idempotency_key": "optional-key"
    }
    """
    db = await get_db()
    lead = payload.get("lead", {})
    org = payload.get("organization", {})
    channel = "sms"

    # --- Policy Guard Check (C2.1) ---
    allowed, reason = await evaluate_policy_guards(db, lead, org, channel)
    if not allowed:
        logger.info(
            "SendBlocked",
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
            "request": payload,
        }

    # --- Provider Send ---
    try:
        ref = await sms_client.send(
            to=payload["to"],
            body=payload["body"],
            idempotency_key=payload.get("idempotency_key"),
        )
        # Log outbound message for telemetry
        await repo.log_outbound(
            enrollment_id=enrollment_id,
            channel=channel,
            provider_ref=ref,
        )
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
