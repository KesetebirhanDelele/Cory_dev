"""
VoiceConversationAgent
----------------------------------------------------------
Facilitates AI-driven voice conversations for admissions outreach.

Responsibilities:
- Initiates or simulates voice calls (via Synthflow)
- Collects or polls transcripts from `message` table
- Uses ConversationalResponseAgent to classify and summarize outcomes
- Persists transcript, intent, and next_action to Supabase
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
        """
        log.info("🎙️ VoiceConversationAgent starting for lead %s", lead_id)

        # --- 1️⃣ Retrieve transcript text (simulated or real) ---
        if simulate:
            log.info("🧪 Simulating voice transcript for %s", lead_id)
            transcript_text = (
                "agent: Hello, this is Cory Admissions!\n"
                "lead: Hi, I’m still deciding about enrolling."
            )
        else:
            try:
                res = await send_voice_call(org_id, enrollment_id, phone, vars=vars or {})
                provider_ref = res.get("provider_ref")
                log.info("📞 Live call initiated with provider_ref=%s", provider_ref)
                transcript_text = await self._collect_transcript(provider_ref)
            except Exception as e:
                log.exception("❌ Failed to initiate Synthflow call: %s", e)
                transcript_text = ""

        # --- 2️⃣ Classify conversation via ConversationalResponseAgent ---
        classification = await self.conv_agent.classify_message(transcript_text)

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
        """
        campaign_name = generated_msg["context"]["campaign"].get("name", "Admissions Campaign")
        outbound_text = generated_msg.get("message_text", "Hello! This is Cory Admissions calling to follow up.")
        log.info("📢 Initiating campaign-based voice call for %s (%s)", lead_id, campaign_name)

        if simulate:
            transcript = f"agent: {outbound_text}\nlead: I'm interested, but not ready to enroll yet."
        else:
            org_id = generated_msg["context"]["campaign"].get("organization_id", "org1")
            try:
                res = await send_voice_call(org_id, enrollment_id, phone, vars={"script": outbound_text})
                provider_ref = res.get("provider_ref")
                transcript = await self._collect_transcript(provider_ref)
            except Exception as e:
                log.exception("Synthflow voice call failed: %s", e)
                transcript = f"agent: {outbound_text}\nlead: Sorry, I missed the call."

        # Classify the final transcript
        classification = await self.conv_agent.classify_message(transcript)

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
                if message and message.get("status") == "complete":
                    # Prefer explicit 'transcript' column if present, else JSON content
                    transcript = message.get("transcript") or (
                        message.get("content", {}).get("transcript")
                        if isinstance(message.get("content"), dict)
                        else None
                    )
                    if transcript:
                        log.info("📝 Transcript retrieved for %s", call_id)
                        return transcript
            except Exception as e:
                log.warning("Error while fetching transcript: %s", e)
            await asyncio.sleep(5)
        log.warning("⚠️ Timeout waiting for transcript for %s", call_id)
        return ""

    # ------------------------------------------------------------------
    # 💾 Persistence
    # ------------------------------------------------------------------
    async def _persist_results(
        self, step_id: str, transcript: str, classification: Dict[str, Any]
    ):
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
        except Exception as e:
            log.exception("❌ Failed to persist voice call results: %s", e)

    # ------------------------------------------------------------------
    # 🔔 Workflow Notification
    # ------------------------------------------------------------------
    async def _notify_workflow(self, lead_id: str, classification: Dict[str, Any]):
        """
        Trigger human follow-up or next automation step based on AI classification.
        """
        intent = classification.get("intent")
        next_action = classification.get("next_action")

        if intent == "ready_to_enroll":
            log.info("📞 Lead %s ready to enroll → scheduling human appointment", lead_id)
            try:
                await self.supabase.create_appointment_task(lead_id)
            except Exception as e:
                log.warning("⚠️ Failed to create appointment task: %s", e)
        else:
            log.info("➡️ Lead %s classified as %s → next_action=%s", lead_id, intent, next_action)
