# app/orchestrator/temporal/activities/voice_start.py

from typing import Dict, Any
import logging

from temporalio import activity

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

    ✔ Policy + budget guards (when context is present)
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
    skip_guards = bool(payload.get("skip_guards", False))
    simulate = bool(payload.get("simulate", False))

    lead = payload.get("lead") or {}
    org = payload.get("organization") or {}
    campaign_id = payload.get("campaign_id")

    # --------------------------------------------------
    # Context extraction
    # --------------------------------------------------
    org_id = org.get("id")
    lead_id = lead.get("id")

    missing_context = not org_id or not lead_id

    if missing_context:
        # This is exactly what was happening for MissedCallFollowupWorkflow:
        # it calls voice_start with just enrollment_id + phone + campaign_id.
        logger.warning(
            "VoiceStartMissingContext",
            extra={
                "enrollment_id": enrollment_id,
                "org_present": bool(org),
                "lead_present": bool(lead),
                "skip_guards_initial": skip_guards,
            },
        )
        # If we don't know org/lead, *force* guards off so we don't
        # try to run policy/budget checks that depend on them.
        skip_guards = True

    # We still derive "best effort" IDs for logging / agent:
    org_id_for_call = org_id or payload.get("org_id")
    lead_id_for_call = lead_id or payload.get("lead_id") or enrollment_id

    logger.info(
        "VoiceStartActivityBegin",
        extra={
            "enrollment_id": enrollment_id,
            "to": to,
            "org_id_for_call": org_id_for_call,
            "lead_id_for_call": lead_id_for_call,
            "campaign_id": campaign_id,
            "skip_guards": skip_guards,
            "simulate": simulate,
        },
    )

    # --------------------------------------------------
    # Acquire Repo
    # --------------------------------------------------
    supabase_repo = SupabaseRepo()

    # --------------------------------------------------
    # Policy Guard Check  (ONLY when we have full context)
    # --------------------------------------------------
    if not skip_guards and org_id and lead_id:
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
    # Budget Guard Check  (ONLY when we have org + campaign_id)
    # --------------------------------------------------
    if not skip_guards and campaign_id and org_id:
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
            await log_decision_to_audit(lead_id_for_call, channel, reason)
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
            org_id=org_id_for_call,
            enrollment_id=enrollment_id,  # ✅ FIXED: no more typo
            phone=to,
            lead_id=lead_id_for_call,
            campaign_step_id=payload.get("campaign_step_id"),
            vars=payload.get("context", {}),
            simulate=simulate,
        )

        # Do NOT lie about success
        status = result.get("status", "unknown")
        if status != "initiated":
            logger.warning(
                "VoiceCallNotInitiated",
                extra={"enrollment_id": enrollment_id, "result": result},
            )
            raise RuntimeError(f"Voice call not initiated: {result}")

        provider_ref = result.get("provider_ref")

        logger.info(
            "VoiceCallInitiated",
            extra={
                "enrollment_id": enrollment_id,
                "lead_id": lead_id_for_call,
                "provider_ref": provider_ref,
                "simulate": simulate,
            },
        )

        return {
            "channel": channel,
            "status": "initiated",
            "provider_ref": provider_ref,
            "enrollment_id": enrollment_id,
        }

    except Exception as e:  # noqa: BLE001
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
