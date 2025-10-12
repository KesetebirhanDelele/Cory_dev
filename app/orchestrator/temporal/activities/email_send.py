from temporalio import activity
from typing import Dict, Any
import logging

from app.channels.providers import email as email_client
from app.data import supabase_repo as repo
from app.policy.guards import evaluate_policy_guards
from app.policy.guards_budget import evaluate_budget_caps
from app.data.telemetry import log_decision_to_audit  # optional
from app.data.db import get_pool  # your db helper in app/data/db.py

logger = logging.getLogger(__name__)


@activity.defn(name="email_send")
async def email_send(enrollment_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send an email through the configured Mandrill provider.
    Enforces quiet hours, consent, frequency, and budget/rate caps before sending.

    payload example:
    {
        "lead": {...},
        "organization": {...},
        "to": "user@example.edu",
        "template": "welcome_template",
        "variables": {"first_name": "Alex"},
        "subject": "Welcome to Admissions!",
        "campaign_id": "CAMP123"
    }
    """
    channel = "email"
    lead = payload.get("lead", {})
    org = payload.get("organization", {})
    campaign_id = payload.get("campaign_id")

    # --- Acquire DB connection or pool -------------------------------------
    db = await get_pool()

    # --- Policy Guard Check (C2.1: quiet/consent/frequency) -----------------
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
        ref = await email_client.send_email(
            to_email=payload["to"],
            subject=payload.get("subject"),
            template_name=payload.get("template"),
            variables=payload.get("variables", {}),
        )

        # Optional: record outbound for telemetry/audit
        try:
            await repo.log_outbound(
                enrollment_id=enrollment_id,
                channel=channel,
                provider_ref=ref,
            )
        except Exception as log_ex:
            logger.warning("OutboundLogFailed", extra={"error": str(log_ex)})

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
