# app/agents/campaign_message_agent.py
"""
CampaignMessageGeneratorAgent:
Generates personalized outbound messages for campaign steps.
Integrates with ConversationalResponseAgent and VoiceConversationAgent
for contextual, AI-driven communication workflows.
"""

import os
import logging
from datetime import datetime
from typing import Dict, Any

from dotenv import load_dotenv
from openai import OpenAI
from supabase import create_client, Client

# ---------------------------------------------------------------------
# 🔧 Environment & Logging Setup
# ---------------------------------------------------------------------
load_dotenv()
logger = logging.getLogger("cory.campaign.agent")
logging.basicConfig(level=logging.INFO)


class CampaignMessageGeneratorAgent:
    """
    Generates personalized outreach messages using data from Supabase
    and OpenAI GPT models. Context is drawn from enrollment, campaign,
    contact (lead), and campaign step tables.
    """

    def __init__(self):
        # --- Supabase setup ---
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

        if not url or not key:
            raise ValueError(f"Missing Supabase credentials. Got URL={url}, KEY={'set' if key else 'None'}")

        self.supabase: Client = create_client(url, key)

        # --- OpenAI setup ---
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("Missing OPENAI_API_KEY in environment variables.")
        self.openai = OpenAI(api_key=api_key)

    # ---------------------------------------------------------------------
    # 🔹 Main public methods
    # ---------------------------------------------------------------------
    async def async_generate_message(self, registration_id: str, channel: str) -> Dict[str, Any]:
        """Async wrapper for workflow orchestration."""
        return self.generate_message(registration_id, channel)

    def generate_message(self, registration_id: str, channel: str) -> Dict[str, Any]:
        """
        Generate an AI-personalized campaign message.
        Pulls context from Supabase and uses OpenAI to produce text
        appropriate for the specified communication channel.
        """
        logger.info(f"🎯 Generating {channel} message for registration_id={registration_id}")

        # 1️⃣ Pull context
        context = self._fetch_context(registration_id)
        if not context:
            raise ValueError(f"No enrollment found for registration_id={registration_id}")

        # 2️⃣ Build LLM prompt
        prompt = self._build_prompt(context, channel)

        # 3️⃣ Call OpenAI
        try:
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a helpful admissions outreach assistant."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.8,
                max_tokens=250,
            )
            text = response.choices[0].message.content.strip()
        except Exception as e:
            logger.exception("OpenAI error generating message:")
            text = "Hi there! We’re excited to help you explore your next steps with our programs."

        # 4️⃣ Assemble structured message payload
        payload = {
            "registration_id": registration_id,
            "channel": channel,
            "text": text,
            "tone": self._infer_tone(channel),
            "cta": self._generate_cta(channel),
            "timestamp": datetime.utcnow().isoformat(),
            "context": context,
        }

        # 5️⃣ Log event for auditing
        self._log_generation_event(
            registration_id,
            context["enrollment"].get("project_id", ""),
            channel,
            message_text=text,
        )

        logger.info(f"✅ Generated {channel} message for {registration_id}: {text[:100]}...")

        # ✅ Return standardized format compatible with ConversationalResponseAgent
        return {
            "message_text": text,
            "context": context,
            "channel": channel,
            "tone": payload["tone"],
            "cta": payload["cta"],
        }

    # ---------------------------------------------------------------------
    # 🔹 Context Builders & Helpers
    # ---------------------------------------------------------------------
    def _fetch_context(self, registration_id: str) -> Dict[str, Any]:
        """
        Retrieves campaign context from Supabase:
        - enrollment
        - contact (lead)
        - campaign
        - latest lead_campaign_step
        """

        # Enrollment
        enrollment_res = (
            self.supabase.table("enrollment")
            .select("*")
            .eq("registration_id", registration_id)
            .execute()
        )
        if not enrollment_res.data:
            return {}
        enrollment = enrollment_res.data[0]

        # Contact (lead)
        contact_res = (
            self.supabase.table("contact")
            .select("first_name,last_name,email,phone")
            .eq("id", enrollment["contact_id"])
            .execute()
        )
        contact = contact_res.data[0] if contact_res.data else {}
        contact["name"] = f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip() or "Student"

        # Campaign
        campaign_res = (
            self.supabase.table("campaigns")
            .select("id,name,description,is_active,organization_id")
            .eq("id", enrollment["campaign_id"])
            .execute()
        )
        campaign = campaign_res.data[0] if campaign_res.data else {}

        # Step (latest)
        step_res = (
            self.supabase.table("lead_campaign_steps")
            .select("step_name,step_type,status")
            .eq("registration_id", registration_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        step = step_res.data[0] if step_res.data else {}

        return {
            "lead": contact,
            "campaign": campaign,
            "step": step,
            "enrollment": enrollment,
        }

    def _build_prompt(self, context: Dict[str, Any], channel: str) -> str:
        """Compose the full LLM prompt from campaign + enrollment context."""
        lead = context.get("lead", {})
        campaign = context.get("campaign", {})
        step = context.get("step", {})
        enrollment = context.get("enrollment", {})

        name = lead.get("name", "Student")
        field = enrollment.get("field_of_study", "your program of interest")
        campaign_name = campaign.get("name", "Admissions Outreach")
        step_name = step.get("step_name", "Introduction")
        goal = step.get("goal", "encourage engagement")
        tone = self._infer_tone(channel)
        cta = self._generate_cta(channel)

        return (
            f"You are an admissions outreach assistant crafting a {channel} message.\n"
            f"Student name: {name}\n"
            f"Field of study: {field}\n"
            f"Campaign: {campaign_name}\n"
            f"Step: {step_name}\n"
            f"Goal: {goal}\n"
            f"Tone: {tone}\n"
            f"Call to Action: {cta}\n\n"
            f"Write a short, friendly, and personalized {channel} message "
            f"to engage {name} in continuing the admissions process. "
            f"Keep it concise, natural, and appropriate for {channel}. "
            f"Return only the message text."
        )

    def _infer_tone(self, channel: str) -> str:
        tones = {
            "sms": "friendly and concise",
            "email": "professional yet warm",
            "voice": "conversational and upbeat",
        }
        return tones.get(channel, "friendly and helpful")

    def _generate_cta(self, channel: str) -> str:
        ctas = {
            "sms": "Reply YES to schedule a quick chat!",
            "email": "Click below to schedule your consultation.",
            "voice": "Press 1 to connect with an advisor now.",
        }
        return ctas.get(channel, "Let's connect soon!")

    # ---------------------------------------------------------------------
    # 🔹 Logging Helper
    # ---------------------------------------------------------------------
    def _log_generation_event(self, registration_id: str, project_id: str, channel: str, message_text: str):
        """
        Inserts a message generation record in Supabase.event for auditing.
        """
        try:
            enrollment_result = (
                self.supabase.table("enrollment")
                .select("id")
                .eq("registration_id", registration_id)
                .execute()
            )
            if not enrollment_result.data:
                logger.warning(f"No enrollment found for registration_id={registration_id}")
                return

            enrollment_id = enrollment_result.data[0]["id"]

            event_data = {
                "project_id": project_id,
                "enrollment_id": enrollment_id,
                "event_type": "message_generated",
                "direction": "outbound",
                "payload": {
                    "channel": channel,
                    "message_preview": message_text[:120],
                },
                "created_at": datetime.utcnow().isoformat(),
            }

            self.supabase.table("event").insert(event_data).execute()
            logger.info(f"🪵 Logged message generation event for enrollment_id={enrollment_id}")
        except Exception as e:
            logger.warning(f"Failed to log generation event: {e}")
