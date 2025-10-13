from temporalio import activity
from typing import Dict, Any
import logging

from app.channels.providers import voice as voice_client
from app.data import supabase_repo as repo
from app.policy.guards import evaluate_policy_guards
from app.policy.guards_budget import evaluate_budget_caps
from app.data.telemetry import log_decision_to_audit
from app.data.db import supabase  # consistent with other activities

logger = logging.getLogger(__name__)


@activity.defn(name="voice_start")
async def voice_start(enrollment_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Start an outbound Synthflow call (voice channel).
    Applies quiet hours, consent, frequency, and budget/rate caps pre-send.

    payload example:
    {
        "lead": {...},
        "organization": {...},
        "to": "+15551234567",
        "agent_id": "voice_agent_001",
        "context": {"program": "nursing"},
        "campaign_id": "CAMP123"
    }
    """
    channel = "voice"
    lead = payload.get("lead", {})
    org = payload.get("organization", {})
    campaign_id = payload.get("campaign_id")

    # --- Acquire DB connection ---------------------------------------------
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
        ref = await voice_client.start_call(
            to=payload["to"],
            agent_id=payload["agent_id"],
            context=payload.get("context", {}),
        )

        # Optional: log outbound call for telemetry/audit
        try:
            await repo.log_outbound(
                enrollment_id=enrollment_id,
                channel=channel,
                provider_ref=ref,
            )
        except Exception as log_ex:
            logger.warning("OutboundLogFailed", extra={"error": str(log_ex)})

        logger.info(
            "VoiceDispatched",
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
            "VoiceError",
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
