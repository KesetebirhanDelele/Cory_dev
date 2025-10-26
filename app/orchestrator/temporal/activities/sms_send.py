# app/orchestrator/temporal/activities/sms_send.py
from temporalio import activity
from typing import Dict, Any
import logging
from app.channels.providers import sms as sms_client
from app.data import supabase_repo as repo
from app.policy.guards import evaluate_policy_guards
from app.policy.guards_budget import evaluate_budget_caps
from app.data.telemetry import log_decision_to_audit
from app.data.db import supabase  # async supabase accessor

logger = logging.getLogger(__name__)

@activity.defn(name="sms_send")
async def sms_send(enrollment_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Temporal activity: send an SMS message via Cory's configured provider.
    Integrates policy guards, budget caps, idempotency, and audit logging.

    payload = {
        "to": "+15551234567",
        "body": "Hi there!",
        "lead": {...},
        "organization": {...},
        "campaign_id": "CAMP123",
        "idempotency_key": "optional-key"
    }
    """
    activity.logger.info(f"📨 [SMS_SEND] Starting send for enrollment={enrollment_id}")

    channel = "sms"
    lead = payload.get("lead", {})
    org = payload.get("organization", {})
    campaign_id = payload.get("campaign_id")

    # --- Policy Guard (quiet hours, consent, etc.) ---
    allowed, reason = await evaluate_policy_guards(supabase, lead, org, channel)
    if not allowed:
        activity.logger.info(f"🚫 Policy blocked SMS: {reason}")
        await log_decision_to_audit(lead.get("id"), channel, reason)
        return {
            "channel": channel,
            "enrollment_id": enrollment_id,
            "status": "blocked",
            "stage": "policy_guard",
            "reason": reason,
            "request": payload,
        }

    # --- Budget / Rate Cap Check ---
    allowed, reason, hint = await evaluate_budget_caps(
        db=supabase, campaign_id=campaign_id, channel=channel, policy=org.get("policy", {})
    )
    if not allowed:
        activity.logger.info(f"💸 Budget guard blocked SMS: {reason}")
        await log_decision_to_audit(lead.get("id"), channel, reason)
        return {
            "channel": channel,
            "enrollment_id": enrollment_id,
            "status": "blocked",
            "stage": "budget_guard",
            "reason": reason,
            "hint": hint,
            "request": payload,
        }

    # --- Provider Send ---
    try:
        to = payload["to"]
        body = payload["body"]

        activity.logger.info(f"📤 Sending SMS to {to}: {body[:80]}")
        provider_ref = await sms_client.send(
            to=to,
            body=body,
            idempotency_key=payload.get("idempotency_key"),
        )

        # Log outbound record in Supabase
        try:
            await repo.log_outbound(enrollment_id, channel, provider_ref)
        except Exception as ex:
            activity.logger.warning(f"⚠️ Failed to log outbound SMS: {ex}")

        activity.logger.info(
            f"✅ SMS dispatched successfully | to={to} ref={provider_ref}"
        )
        return {
            "channel": channel,
            "enrollment_id": enrollment_id,
            "provider_ref": provider_ref,
            "status": "sent",
            "request": payload,
        }

    except Exception as e:
        activity.logger.error(
            f"❌ SMS send failed | enrollment={enrollment_id} error={e}",
            exc_info=True,
        )
        return {
            "channel": channel,
            "enrollment_id": enrollment_id,
            "status": "failed",
            "error": str(e),
            "request": payload,
        }
