# app/orchestrator/temporal/activities/voice_start.py
from temporalio import activity
from typing import Dict, Any
import logging

from app.agents.voice_conversation_agent import VoiceConversationAgent
from app.data.supabase_repo import SupabaseRepo
from app.policy.guards import evaluate_policy_guards
from app.policy.guards_budget import evaluate_budget_caps
from app.data.telemetry import log_decision_to_audit
from app.data.db import supabase  # consistent with other activities

logger = logging.getLogger(__name__)


@activity.defn(name="voice_start")
async def voice_start(enrollment_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Start an outbound or simulated voice conversation via Synthflow.

    Handles policy and budget guards, runs the call through VoiceConversationAgent,
    captures transcript + intent classification, and updates Supabase.
    """

    channel = "voice"
    lead = payload.get("lead", {})
    org = payload.get("organization", {})
    campaign_id = payload.get("campaign_id")
    simulate = payload.get("simulate", False)
    to = payload.get("to")

    # --- Acquire DB / Repo --------------------------------------------------
    db = supabase
    supabase_repo = SupabaseRepo(db)

    # --- Policy Guard Check -------------------------------------------------
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

    # --- Budget / Rate Cap Check -------------------------------------------
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

    # --- Execute Voice Conversation ----------------------------------------
    try:
        agent = VoiceConversationAgent(supabase_repo)
        result = await agent.start_call(
            org_id=org.get("id"),
            enrollment_id=enrollment_id,
            phone=to,
            lead_id=lead.get("id"),
            campaign_step_id=payload.get("campaign_step_id"),
            vars=payload.get("context", {}),
            simulate=simulate,
        )

        # Combine result and return structured data
        logger.info(
            "VoiceConversationCompleted",
            extra={
                "enrollment_id": enrollment_id,
                "lead_id": lead.get("id"),
                "intent": result.get("intent"),
                "next_action": result.get("next_action"),
            },
        )
        return {
            "channel": channel,
            "enrollment_id": enrollment_id,
            "lead_id": lead.get("id"),
            "intent": result.get("intent"),
            "next_action": result.get("next_action"),
            "status": "completed",
            "transcript_saved": True,
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
            "lead_id": lead.get("id"),
            "status": "failed",
            "error": str(e),
            "request": payload,
        }
