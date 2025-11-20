# app/agents/voice_conversation_agent.py
"""
VoiceConversationAgent
----------------------------------------------------------
Facilitates AI-driven voice conversations for admissions outreach.

Responsibilities:
- Initiates or simulates voice calls (via Synthflow)
- Collects or polls transcripts from `message` table
- Uses ConversationalResponseAgent to classify and summarize outcomes
- Persists transcript, intent, next_action, prompt_used, provider_ref to Supabase
- Triggers follow-up workflows for "ready_to_enroll" leads
"""

import asyncio
import logging
from datetime import datetime, UTC
from typing import Dict, Any

from app.agents.conversational_response_agent import ConversationalResponseAgent
from app.channels.providers.voice import send_voice_call
from app.data.supabase_repo import SupabaseRepo

log = logging.getLogger("cory.voice.agent")
log.setLevel(logging.INFO)


class VoiceConversationAgent:
    """
    Coordinates voice calls and leverages ConversationalResponseAgent
    for AI-driven classification and next-action inference.
    """

    def __init__(self, supabase: SupabaseRepo):
        self.supabase = supabase
        self.conv_agent = ConversationalResponseAgent()

    # ------------------------------------------------------------------
    # 🎙️ Primary Entry Point (Generic)
    # ------------------------------------------------------------------
    async def start_call(
        self,
        org_id: str,
        enrollment_id: str,
        phone: str,
        lead_id: str,
        campaign_step_id: str,
        vars: Dict[str, Any] | None = None,
        simulate: bool = False,
    ) -> Dict[str, Any]:
        """
        Starts a live or simulated voice conversation and classifies outcome.

        If vars contains a 'prompt' key, it will be passed through to
        send_voice_call for dynamic prompt override and recorded as
        prompt_used on the lead_campaign_step.
        """
        log.info("🎙️ VoiceConversationAgent starting for lead %s", lead_id)
        vars = vars or {}

        # --- 1️⃣ Retrieve transcript text (simulated or real) ---
        if simulate:
            log.info("🧪 Simulating voice transcript for %s", lead_id)
            transcript_text = (
                "agent: Hello, this is Cory Admissions!\n"
                "lead: Hi, I’m still deciding about enrolling."
            )
        else:
            try:
                res = await send_voice_call(org_id, enrollment_id, phone, vars=vars)
                provider_ref = res.get("provider_ref")
                log.info("📞 Live call initiated with provider_ref=%s", provider_ref)

                # Persist prompt_used/provider_ref/start time if we have a campaign_step_id
                prompt_used = vars.get("prompt")
                if campaign_step_id:
                    await self.supabase.update_lead_campaign_step(
                        campaign_step_id,
                        {
                            "prompt_used": prompt_used,
                            "provider_ref": provider_ref,
                            "started_at": datetime.now(UTC).isoformat(),
                        },
                    )

                transcript_text = await self._collect_transcript(provider_ref)
            except Exception as e:  # noqa: BLE001
                log.exception("❌ Failed to initiate Synthflow call: %s", e)
                transcript_text = ""

        # --- 2️⃣ Classify conversation via ConversationalResponseAgent ---
        classification = await self.conv_agent.classify_message(
            transcript_text,
            channel="voice",
        )

        # --- 3️⃣ Persist transcript + classification ---
        await self._persist_results(campaign_step_id, transcript_text, classification)

        # --- 4️⃣ Trigger workflow follow-up (if needed) ---
        await self._notify_workflow(lead_id, classification)

        log.info("✅ VoiceConversationAgent finished for %s", lead_id)
        return classification

    # ------------------------------------------------------------------
    # 🧩 Campaign Integration Entry Point
    # ------------------------------------------------------------------
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
        Handles a campaign-generated voice message (from CampaignMessageGeneratorAgent),
        simulates or executes a call, then classifies conversation result.

        For live calls, uses dynamic prompt override:
        - Builds a prompt from lead/campaign/enrollment context
        - Injects the LLM-generated voice script as part of that prompt
        - Stores prompt_used + provider_ref on lead_campaign_steps
        """
        context = generated_msg.get("context", {}) or {}
        campaign_ctx = context.get("campaign", {}) or {}
        lead_ctx = context.get("lead", {}) or {}
        enrollment_ctx = context.get("enrollment", {}) or {}

        campaign_name = campaign_ctx.get("name", "Admissions Campaign")
        outbound_text = generated_msg.get(
            "message_text",
            "Hi there, this is Cory Admissions calling to follow up on your interest in our programs.",
        )

        lead_first = (lead_ctx.get("first_name") or "").strip()
        lead_last = (lead_ctx.get("last_name") or "").strip()
        lead_name = f"{lead_first} {lead_last}".strip() or "there"

        program_interest = (
            enrollment_ctx.get("program_interest")
            or lead_ctx.get("field_of_study")
            or "your program of interest"
        )
        start_term = enrollment_ctx.get("start_term") or "an upcoming term"

        log.info(
            "📢 Initiating campaign-based voice call for %s (%s)",
            lead_id,
            campaign_name,
        )

        if simulate:
            # Simple simulated transcript
            transcript = (
                f"agent: {outbound_text}\n"
                "lead: I'm interested, but not ready to enroll yet."
            )
        else:
            org_id = campaign_ctx.get("organization_id", "org1")

            # Build dynamic prompt for Synthflow
            dynamic_prompt = (
                "You are Cory, an AI admissions assistant for Cory College.\n"
                "You are calling a prospective student about enrolling.\n\n"
                f"Student name: {lead_name}\n"
                f"Program interest: {program_interest}\n"
                f"Preferred start term: {start_term}\n"
                f"Campaign name: {campaign_name}\n\n"
                "Use the following outreach script as a flexible guide. "
                "Speak naturally, ask clarifying questions, and determine if the student is:\n"
                "- ready_to_enroll\n"
                "- interested_but_not_ready\n"
                "- unsure_or_declined\n"
                "- not_interested\n"
                "- callback_requested (e.g., 'call me later')\n"
                "- voicemail/no_answer\n"
                "- unclassified/low confidence\n\n"
                "Outreach script:\n"
                f"{outbound_text}\n\n"
                "At the end of the call, summarize their intent internally so the system "
                "can choose the next action based on your transcript."
            )

            try:
                # Pass dynamic prompt override + lead_name to provider
                vars = {
                    "prompt": dynamic_prompt,  # 🔥 dynamic prompt override for Synthflow
                    "lead_name": lead_name,
                }
                res = await send_voice_call(org_id, enrollment_id, phone, vars=vars)
                provider_ref = res.get("provider_ref")
                log.info("📞 Live campaign call initiated with provider_ref=%s", provider_ref)

                # Persist prompt + provider_ref + started_at on this campaign step
                await self.supabase.update_lead_campaign_step(
                    step_id,
                    {
                        "prompt_used": dynamic_prompt,
                        "provider_ref": provider_ref,
                        "started_at": datetime.now(UTC).isoformat(),
                    },
                )

                transcript = await self._collect_transcript(provider_ref)
            except Exception as e:  # noqa: BLE001
                log.exception("Synthflow voice call failed: %s", e)
                transcript = f"agent: {outbound_text}\nlead: Sorry, I missed the call."

        # Classify the final transcript
        classification = await self.conv_agent.classify_message(
            transcript,
            channel="voice",
        )

        # Persist in Supabase
        await self._persist_results(step_id, transcript, classification)
        await self._notify_workflow(lead_id, classification)

        log.info("✅ Campaign-based voice interaction complete for %s", lead_id)
        return classification

    # ------------------------------------------------------------------
    # 🧠 Transcript Collection (via message table)
    # ------------------------------------------------------------------
    async def _collect_transcript(self, call_id: str, timeout: int = 60) -> str:
        """
        Poll Supabase `message` table for the transcript created via voice webhook.
        """
        log.info("⌛ Waiting for transcript from Synthflow for call_id=%s", call_id)
        for _ in range(timeout // 5):
            try:
                message = await self.supabase.get_message_by_provider_ref(call_id)
                # Status from Synthflow webhook is typically "completed"
                if message and message.get("status") in ("completed", "sent"):
                    # Prefer explicit 'transcript' column if present, else JSON content
                    transcript = message.get("transcript") or (
                        message.get("content", {}).get("transcript")
                        if isinstance(message.get("content"), dict)
                        else None
                    )
                    if transcript:
                        log.info("📝 Transcript retrieved for %s", call_id)
                        return transcript
            except Exception as e:  # noqa: BLE001
                log.warning("Error while fetching transcript: %s", e)
            await asyncio.sleep(5)

        log.warning("⚠️ Timeout waiting for transcript for %s", call_id)
        return ""

    # ------------------------------------------------------------------
    # 💾 Persistence
    # ------------------------------------------------------------------
    async def _persist_results(
        self,
        step_id: str,
        transcript: str,
        classification: Dict[str, Any],
    ) -> None:
        """
        Save transcript + AI classification results to Supabase.
        """
        try:
            payload = {
                "transcript": transcript,
                "intent": classification.get("intent"),
                "next_action": classification.get("next_action"),
                "updated_at": datetime.now(UTC).isoformat(),
            }
            await self.supabase.update_lead_campaign_step(step_id, payload)
            log.info("🧾 Stored transcript + intent for step %s", step_id)
        except Exception as e:  # noqa: BLE001
            log.exception("❌ Failed to persist voice call results: %s", e)

    # ------------------------------------------------------------------
    # 🔔 Workflow Notification
    # ------------------------------------------------------------------
    async def _notify_workflow(self, lead_id: str, classification: Dict[str, Any]) -> None:
        """
        Trigger human follow-up or next automation step based on AI classification.
        """
        intent = classification.get("intent")
        next_action = classification.get("next_action")

        if intent == "ready_to_enroll":
            log.info("📞 Lead %s ready to enroll → scheduling human appointment", lead_id)
            try:
                await self.supabase.create_appointment_task(lead_id)
            except Exception as e:  # noqa: BLE001
                log.warning("⚠️ Failed to create appointment task: %s", e)
        else:
            log.info("➡️ Lead %s classified as %s → next_action=%s", lead_id, intent, next_action)
