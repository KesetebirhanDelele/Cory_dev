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

    For channel="voice", the generated message is a natural call script
    that can be passed directly into Synthflow via dynamic prompt override.
    """

    def __init__(self):
        # --- Supabase setup ---
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

        if not url or not key:
            raise ValueError(
                f"Missing Supabase credentials. Got URL={url}, KEY={'set' if key else 'None'}"
            )

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

        For channel="voice", the returned `message_text` is a phone script
        suitable for use as the Synthflow script in a dynamic prompt override.
        """
        logger.info("🎯 Generating %s message for registration_id=%s", channel, registration_id)

        # 1️⃣ Pull context (includes enrollment, contact, campaign, latest step)
        context = self._fetch_context(registration_id)
        if not context:
            raise ValueError(f"No enrollment found for registration_id={registration_id}")

        # 2️⃣ Build LLM prompt (voice vs sms vs email-specific guidance)
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
            text = (response.choices[0].message.content or "").strip()
        except Exception:
            logger.exception("OpenAI error generating message:")
            # Fallback generic text if LLM fails
            if channel == "voice":
                text = (
                    "Hi there, this is Cory from Admissions. "
                    "I’m calling to follow up on your interest in our programs and see how we can help "
                    "with your next steps toward enrollment."
                )
            elif channel == "sms":
                text = (
                    "Hi there, this is Cory from Admissions. "
                    "Just checking in about your interest in our programs. "
                    "Reply YES if you’d like help with next steps."
                )
            else:  # email
                text = (
                    "Hi there,\n\n"
                    "Thanks again for your interest in our programs. "
                    "We’d love to help you review your options and next steps toward enrollment.\n\n"
                    "– Cory Admissions Team"
                )

        tone = self._infer_tone(channel)
        cta = self._generate_cta(channel)

        # 4️⃣ Assemble structured message payload
        payload = {
            "registration_id": registration_id,
            "channel": channel,
            "text": text,
            "tone": tone,
            "cta": cta,
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

        logger.info("✅ Generated %s message for %s: %s...", channel, registration_id, text[:100])

        # ✅ Return standardized format compatible with VoiceConversationAgent, etc.
        return {
            "message_text": text,   # voice script / sms body / email body
            "context": context,     # includes campaign.id/name/organization_id
            "channel": channel,
            "tone": tone,
            "cta": cta,
        }

    # ---------------------------------------------------------------------
    # 🔹 Context Builders & Helpers
    # ---------------------------------------------------------------------
    def _fetch_context(self, registration_id: str) -> Dict[str, Any]:
        """
        Retrieves campaign context from Supabase:
        - enrollment (including program_interest, start_term, preferred_channel)
        - contact (lead; includes field_of_study)
        - campaign
        - latest lead_campaign_step
        """

        # Enrollment (registration-level record)
        enrollment_res = (
            self.supabase.table("enrollment")
            .select(
                "id, project_id, campaign_id, contact_id, status, "
                "program_interest, start_term, preferred_channel"
            )
            .eq("registration_id", registration_id)
            .execute()
        )
        if not enrollment_res.data:
            return {}
        enrollment = enrollment_res.data[0]

        # Contact (lead)
        contact_res = (
            self.supabase.table("contact")
            .select("first_name,last_name,email,phone,field_of_study,source")
            .eq("id", enrollment["contact_id"])
            .execute()
        )
        contact = contact_res.data[0] if contact_res.data else {}
        contact["name"] = (
            f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip() or "Student"
        )

        # Campaign
        campaign_res = (
            self.supabase.table("campaigns")
            .select("id,name,description,is_active,organization_id")
            .eq("id", enrollment["campaign_id"])
            .execute()
        )
        campaign = campaign_res.data[0] if campaign_res.data else {}

        # Step (latest for this registration)
        step_res = (
            self.supabase.table("lead_campaign_steps")
            .select("step_name,step_type,status,created_at")
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
        """
        Compose the full LLM prompt from campaign + enrollment context.

        For voice, we explicitly ask the model for a natural spoken
        phone script (not an SMS or email).
        """
        lead = context.get("lead", {}) or {}
        campaign = context.get("campaign", {}) or {}
        step = context.get("step", {}) or {}
        enrollment = context.get("enrollment", {}) or {}

        name = lead.get("name", "Student")
        program_interest = (
            enrollment.get("program_interest")
            or lead.get("field_of_study")
            or "your program of interest"
        )
        start_term = enrollment.get("start_term") or "an upcoming term"
        preferred_channel = enrollment.get("preferred_channel") or "their preferred contact method"

        campaign_name = campaign.get("name", "Admissions Outreach")
        step_name = step.get("step_name", "Introduction")
        goal = step.get("goal", "encourage engagement and move the student closer to enrollment")

        tone = self._infer_tone(channel)
        cta = self._generate_cta(channel)

        base_context = (
            f"You are an admissions outreach assistant crafting a {channel} message.\n"
            f"Student name: {name}\n"
            f"Program interest: {program_interest}\n"
            f"Start term: {start_term}\n"
            f"Preferred channel: {preferred_channel}\n"
            f"Campaign: {campaign_name}\n"
            f"Step: {step_name}\n"
            f"Goal: {goal}\n"
            f"Tone: {tone}\n"
            f"Call to Action: {cta}\n\n"
        )

        if channel == "voice":
            channel_instructions = (
                "Write a short, friendly, and natural PHONE CALL SCRIPT that an AI caller can read verbatim. "
                "Use first-person voice (\"Hi, this is Cory...\") and address the student by name. "
                "Reference their interest in the program and upcoming term, offer help with next steps, "
                "and end with an open question that invites them to share how ready they feel to enroll. "
                "Return only the spoken script text, without labels like 'Agent:' or 'Student:'."
            )
        elif channel == "sms":
            channel_instructions = (
                "Write a single SMS message (no more than 2 short sentences). "
                "Be friendly and concise, reference the program and upcoming term, "
                "and include a clear prompt for them to reply (e.g., YES/NO or a short answer). "
                "Return only the SMS text."
            )
        elif channel == "email":
            channel_instructions = (
                "Write a short email with a greeting, 2–3 brief sentences about their interest "
                "and upcoming term, and a clear next step (reply, schedule a call, or ask questions). "
                "Return only the email body text (no subject line needed)."
            )
        else:
            channel_instructions = (
                "Write a short, friendly, and personalized message appropriate for this channel. "
                "Return only the message text."
            )

        return base_context + channel_instructions

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
            "email": "Reply to this email or schedule a quick call.",
            "voice": "Invite the student to share how ready they feel and offer to schedule a call.",
        }
        return ctas.get(channel, "Let's connect soon!")

    # ---------------------------------------------------------------------
    # 🔹 Logging Helper
    # ---------------------------------------------------------------------
    def _log_generation_event(
        self,
        registration_id: str,
        project_id: str,
        channel: str,
        message_text: str,
    ) -> None:
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
                logger.warning("No enrollment found for registration_id=%s", registration_id)
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
            logger.info("🪵 Logged message generation event for enrollment_id=%s", enrollment_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to log generation event: %s", e)
