# app/agents/voice_conversation_agent.py

"""
VoiceConversationAgent
----------------------------------------------------------
Responsibilities are now EXPLICITLY split:

1. start_call()
   - Fire-and-forget
   - Used by MissedCallFollowupWorkflow
   - NO transcript polling
   - NO blocking
   - NO retries

2. facilitate_call_from_campaign()
   - Campaign-driven calls
   - May wait for transcript
   - Classifies intent
   - Drives downstream automation
"""

import asyncio
import logging
from datetime import datetime, UTC
from typing import Dict, Any, Optional

from app.channels.providers.voice import send_voice_call
from app.data.supabase_repo import SupabaseRepo
from app.agents.conversational_response_agent import ConversationalResponseAgent

log = logging.getLogger("cory.voice.agent")
log.setLevel(logging.INFO)


class VoiceConversationAgent:
    def __init__(self, supabase_repo: SupabaseRepo):
        self.supabase = supabase_repo
        self.conv_agent = ConversationalResponseAgent()

    # ======================================================
    # 🔥 FIRE-AND-FORGET VOICE CALL (MISSED CALL FOLLOWUP)
    # ======================================================
    async def start_call(
        self,
        org_id: str,
        enrollment_id: str,
        phone: str,
        lead_id: str,
        campaign_step_id: Optional[str] = None,
        vars: Optional[Dict[str, Any]] = None,
        simulate: bool = False,
    ) -> Dict[str, Any]:
        """
        Fire-and-forget outbound voice call.

        ✅ Used by MissedCallFollowupWorkflow
        ❌ NO transcript polling
        ❌ NO blocking
        ❌ NO retries
        """

        vars = vars or {}

        log.info(
            "📞 Initiating fire-and-forget voice call",
            extra={
                "org_id": org_id,
                "enrollment_id": enrollment_id,
                "lead_id": lead_id,
                "phone": phone,
                "simulate": simulate,
            },
        )

        # -------------------------
        # SIMULATION MODE
        # -------------------------
        if simulate:
            log.info("🧪 Simulated voice call (no provider invoked)")
            return {
                "status": "initiated",
                "channel": "voice",
                "simulated": True,
                "lead_id": lead_id,
                "enrollment_id": enrollment_id,
            }

        # -------------------------
        # REAL PROVIDER CALL
        # -------------------------
        try:
            res = await send_voice_call(
                org_id=org_id,
                enrollment_id=enrollment_id,
                to=phone,
                vars=vars,
            )

            provider_ref = res.get("provider_ref")

            log.info(
                "📞 Voice call successfully initiated",
                extra={"provider_ref": provider_ref},
            )

            # Persist ONLY metadata (never transcript)
            if campaign_step_id:
                await self.supabase.update_lead_campaign_step(
                    campaign_step_id,
                    {
                        "provider_ref": provider_ref,
                        "started_at": datetime.now(UTC).isoformat(),
                    },
                )

            return {
                "status": "initiated",
                "channel": "voice",
                "provider_ref": provider_ref,
                "lead_id": lead_id,
                "enrollment_id": enrollment_id,
            }

        except Exception as e:  # noqa: BLE001
            log.exception("❌ Voice provider call failed (non-blocking)")
            return {
                "status": "failed",
                "channel": "voice",
                "lead_id": lead_id,
                "enrollment_id": enrollment_id,
                "error": str(e),
            }

    # ======================================================
    # 🎯 CAMPAIGN-DRIVEN VOICE CALL (WITH TRANSCRIPT)
    # ======================================================
    async def facilitate_call_from_campaign(
        self,
        generated_msg: Dict[str, Any],
        enrollment_id: str,
        lead_id: str,
        phone: str,
        step_id: str,
        simulate: bool = True,
    ) -> Dict[str, Any]:
        """
        Campaign-driven call.
        - May wait for transcript
        - Classifies intent
        - Drives next actions
        """

        context = generated_msg.get("context", {}) or {}
        campaign_ctx = context.get("campaign", {}) or {}
        lead_ctx = context.get("lead", {}) or {}
        enrollment_ctx = context.get("enrollment", {}) or {}

        outbound_text = generated_msg.get(
            "message_text",
            "Hi, this is Cory Admissions calling to follow up.",
        )

        lead_name = (
            f"{lead_ctx.get('first_name', '').strip()} "
            f"{lead_ctx.get('last_name', '').strip()}"
        ).strip() or "there"

        log.info(
            "📢 Campaign voice call initiated",
            extra={"lead_id": lead_id, "campaign": campaign_ctx.get("name")},
        )

        # -------------------------
        # SIMULATED CAMPAIGN CALL
        # -------------------------
        if simulate:
            transcript = (
                f"agent: {outbound_text}\n"
                "lead: I'm interested but need more time."
            )
        else:
            org_id = campaign_ctx.get("organization_id")
            vars = {
                "prompt": outbound_text,
                "lead_name": lead_name,
            }

            try:
                res = await send_voice_call(org_id, enrollment_id, phone, vars=vars)
                provider_ref = res.get("provider_ref")

                await self.supabase.update_lead_campaign_step(
                    step_id,
                    {
                        "provider_ref": provider_ref,
                        "started_at": datetime.now(UTC).isoformat(),
                        "prompt_used": outbound_text,
                    },
                )

                transcript = await self._collect_transcript(provider_ref)

            except Exception as e:  # noqa: BLE001
                log.exception("❌ Campaign voice call failed")
                transcript = (
                    f"agent: {outbound_text}\n"
                    "lead: Missed the call."
                )

        classification = await self.conv_agent.classify_message(
            transcript,
            channel="voice",
        )

        await self._persist_results(step_id, transcript, classification)
        await self._notify_workflow(lead_id, classification)

        log.info("✅ Campaign voice interaction completed", extra={"lead_id": lead_id})
        return classification

    # ======================================================
    # 🧠 TRANSCRIPT COLLECTION (CAMPAIGN ONLY)
    # ======================================================
    async def _collect_transcript(self, provider_ref: str, timeout: int = 60) -> str:
        log.info("⌛ Waiting for transcript", extra={"provider_ref": provider_ref})

        for _ in range(timeout // 5):
            try:
                message = await self.supabase.get_message_by_provider_ref(provider_ref)
                if message and message.get("transcript"):
                    return message["transcript"]
            except Exception as e:  # noqa: BLE001
                log.warning("Transcript polling error: %s", e)

            await asyncio.sleep(5)

        log.warning("⚠️ Transcript timeout", extra={"provider_ref": provider_ref})
        return ""

    # ======================================================
    # 💾 PERSISTENCE
    # ======================================================
    async def _persist_results(
        self,
        step_id: str,
        transcript: str,
        classification: Dict[str, Any],
    ) -> None:
        await self.supabase.update_lead_campaign_step(
            step_id,
            {
                "transcript": transcript,
                "intent": classification.get("intent"),
                "next_action": classification.get("next_action"),
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )

    # ======================================================
    # 🔔 FOLLOW-UP TRIGGER
    # ======================================================
    async def _notify_workflow(
        self,
        lead_id: str,
        classification: Dict[str, Any],
    ) -> None:
        if classification.get("intent") == "ready_to_enroll":
            await self.supabase.create_appointment_task(lead_id)
