# app/orchestrator/temporal/activities/voice_start.py

from temporalio import activity
from typing import Dict, Any
import logging

from app.agents.voice_conversation_agent import VoiceConversationAgent
from app.data.supabase_repo import SupabaseRepo
from app.policy.guards import evaluate_policy_guards
from app.policy.guards_budget import evaluate_budget_caps
from app.data.telemetry import log_decision_to_audit
from app.data.db import supabase

logger = logging.getLogger(__name__)


@activity.defn(name="voice_start")
async def voice_start(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fire-and-forget outbound voice call activity.

    ✔ Policy + budget guards
    ✔ Initiates provider call
    ✔ Does NOT wait for transcript
    ✔ Does NOT retry internally
    ✔ Never blocks workflow
    """

    # --------------------------------------------------
    # Validate payload EARLY
    # --------------------------------------------------
    enrollment_id = payload.get("enrollment_id")
    to = payload.get("to")

    if not enrollment_id or not to:
        logger.error(
            "VoiceStartInvalidPayload",
            extra={"payload": payload},
        )
        return {
            "channel": "voice",
            "status": "failed",
            "error": "Missing enrollment_id or destination phone",
        }

    channel = "voice"
    skip_guards = payload.get("skip_guards", False)

    lead = payload.get("lead") or {}
    org = payload.get("organization") or {}
    campaign_id = payload.get("campaign_id")
    simulate = payload.get("simulate", False)

    # --------------------------------------------------
    # HARD REQUIREMENTS (THIS WAS MISSING)
    # --------------------------------------------------
    org_id = org.get("id")
    lead_id = lead.get("id")

    if not org_id or not lead_id:
        logger.error(
            "VoiceStartMissingContext",
            extra={
                "enrollment_id": enrollment_id,
                "org": org,
                "lead": lead,
            },
        )
        return {
            "channel": channel,
            "status": "failed",
            "error": "Missing organization.id or lead.id",
        }

    # --------------------------------------------------
    # Acquire Repo
    # --------------------------------------------------
    supabase_repo = SupabaseRepo()

    # --------------------------------------------------
    # Policy Guard Check
    # --------------------------------------------------
    if not skip_guards:
        allowed, reason = await evaluate_policy_guards(
            supabase, lead, org, channel
        )
        if not allowed:
            logger.info(
                "VoiceBlockedPolicy",
                extra={
                    "enrollment_id": enrollment_id,
                    "lead_id": lead_id,
                    "reason": reason,
                },
            )
            await log_decision_to_audit(lead_id, channel, reason)
            return {
                "channel": channel,
                "enrollment_id": enrollment_id,
                "status": "blocked",
                "stage": "policy_guard",
                "reason": reason,
            }

    # --------------------------------------------------
    # Budget Guard Check
    # --------------------------------------------------
    allowed, reason, hint = await evaluate_budget_caps(
        db=supabase,
        campaign_id=campaign_id,
        channel=channel,
        policy=org.get("policy", {}),
    )

    if not allowed:
        logger.info(
            "VoiceBlockedBudget",
            extra={
                "enrollment_id": enrollment_id,
                "campaign_id": campaign_id,
                "reason": reason,
                "hint": hint,
            },
        )
        await log_decision_to_audit(lead_id, channel, reason)
        return {
            "channel": channel,
            "enrollment_id": enrollment_id,
            "status": "blocked",
            "stage": "budget_guard",
            "reason": reason,
            "hint": hint,
        }

    # --------------------------------------------------
    # Fire-and-forget Voice Call (REAL ATTEMPT)
    # --------------------------------------------------
    try:
        agent = VoiceConversationAgent(supabase_repo)

        result = await agent.start_call(
            org_id=org_id,
            enrollment_id=enrollment_id,
            phone=to,
            lead_id=lead_id,
            campaign_step_id=payload.get("campaign_step_id"),
            vars=payload.get("context", {}),
            simulate=simulate,
        )

        # 🔴 CRITICAL: do NOT lie about success
        if result.get("status") != "initiated":
            raise RuntimeError(f"Voice call not initiated: {result}")

        provider_ref = result.get("provider_ref")

        logger.info(
            "VoiceCallInitiated",
            extra={
                "enrollment_id": enrollment_id,
                "lead_id": lead_id,
                "provider_ref": provider_ref,
            },
        )

        return {
            "channel": channel,
            "status": "initiated",
            "provider_ref": provider_ref,
            "enrollment_id": enrollment_id,
        }

    except Exception as e:
        logger.exception(
            "VoiceStartFailed",
            extra={"enrollment_id": enrollment_id},
        )

        # IMPORTANT: workflow continues, but failure is REAL
        return {
            "channel": channel,
            "status": "failed",
            "enrollment_id": enrollment_id,
            "error": str(e),
        }
