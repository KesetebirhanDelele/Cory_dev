from temporalio import activity
from typing import Dict, Any
import logging

from app.channels.providers import email as email_client
from app.data import supabase_repo as repo
from app.policy.guards import evaluate_policy_guards
from app.data.db import get_db
from app.data.telemetry import log_decision_to_audit  # optional

logger = logging.getLogger(__name__)


@activity.defn(name="email_send")
async def email_send(enrollment_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send an email through the configured Mandrill provider.
    Enforces quiet hours, consent, and frequency caps before sending.

    payload example:
    {
        "lead": {...},
        "organization": {...},
        "to": "user@example.edu",
        "template": "welcome_template",
        "variables": {"first_name": "Alex"},
        "subject": "Welcome to Admissions!"
    }
    """
    db = await get_db()
    lead = payload.get("lead", {})
    org = payload.get("organization", {})
    channel = "email"

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
        ref = await email_client.send_email(
            to_email=payload["to"],
            template_name=payload["template"],
            variables=payload.get("variables", {}),
        )
        await repo.log_outbound(
            enrollment_id=enrollment_id,
            channel=channel,
            provider_ref=ref,
        )
        logger.info(
            "EmailDispatched",
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
            "EmailError",
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
