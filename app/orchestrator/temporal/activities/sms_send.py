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
async def sms_send(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Temporal activity: send an SMS message via Cory's configured provider.

    This activity now follows the "single dict arg" pattern required by the
    Temporal SDK in your environment.

    Supported call shapes:

    1) Full, enrollment-aware send (campaign flow):

       args = {
         "enrollment_id": "ENROLL123",
         "payload": {
             "to": "+15551234567",
             "body": "Hi there!",
             "lead": {...},
             "organization": {...},
             "campaign_id": "CAMP123",
             "idempotency_key": "optional-key"
         }
       }

    2) Lightweight direct send (e.g. auto-replies from AnswerWorkflow):

       args = {
         "to": "+15551234567",
         "body": "Thanks for your message!"
       }

       In this case, policy/budget guards and outbound logging are skipped,
       since we don't have enrollment / lead / org context.
    """

    # Decide which calling convention is being used
    enrollment_id = args.get("enrollment_id")
    if "payload" in args:
        payload: Dict[str, Any] = args.get("payload") or {}
    else:
        # Treat the whole args dict as the payload for lightweight sends
        payload = args

    channel = "sms"
    to = payload.get("to")
    body = payload.get("body")

    if not to or not body:
        raise activity.ApplicationError(
            f"sms_send: missing to/body (to={to!r}, body={body!r})",
            non_retryable=True,
        )

    activity.logger.info(
        "📨 [SMS_SEND] starting send | enrollment=%s | to=%s",
        enrollment_id,
        to,
    )

    lead = payload.get("lead") or {}
    org = payload.get("organization") or {}
    campaign_id = payload.get("campaign_id")

    # Only run guards when we have some campaign/enrollment context
    run_guards = bool(enrollment_id or lead or org or campaign_id)

    if run_guards:
        # --- Policy Guard (quiet hours, consent, etc.) ---
        allowed, reason = await evaluate_policy_guards(supabase, lead, org, channel)
        if not allowed:
            activity.logger.info("🚫 Policy blocked SMS: %s", reason)
            if lead.get("id"):
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
            db=supabase,
            campaign_id=campaign_id,
            channel=channel,
            policy=org.get("policy", {}),
        )
        if not allowed:
            activity.logger.info("💸 Budget guard blocked SMS: %s", reason)
            if lead.get("id"):
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
        activity.logger.info("📤 Sending SMS | to=%s | body=%s", to, body[:80])
        provider_ref = await sms_client.send(
            to=to,
            body=body,
            idempotency_key=payload.get("idempotency_key"),
        )

        # Log outbound record in Supabase only when we have an enrollment_id
        if enrollment_id:
            try:
                await repo.log_outbound(enrollment_id, channel, provider_ref)
            except Exception as ex:
                activity.logger.warning(f"⚠️ Failed to log outbound SMS: {ex}")

        activity.logger.info(
            "✅ SMS dispatched successfully | enrollment=%s | to=%s | ref=%s",
            enrollment_id,
            to,
            provider_ref,
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
            "❌ SMS send failed | enrollment=%s | error=%s",
            enrollment_id,
            e,
            exc_info=True,
        )
        return {
            "channel": channel,
            "enrollment_id": enrollment_id,
            "status": "failed",
            "error": str(e),
            "request": payload,
        }
