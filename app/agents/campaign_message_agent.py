# app/agents/campaign_message_agent.py
# Outbound message generation agent for admissions outreach campaigns.
import os
from dotenv import load_dotenv
import logging
from datetime import datetime
from typing import Dict, Any

from openai import OpenAI
from supabase import create_client, Client

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class CampaignMessageGeneratorAgent:
    """
    Generates personalized outreach messages using data from Supabase
    and OpenAI GPT models. Context is drawn from enrollment, campaign,
    lead, and step tables.
    """

    def __init__(self):
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

        if not url or not key:
            raise ValueError(f"Missing Supabase credentials. Got URL={url}, KEY={'set' if key else 'None'}")

        self.supabase: Client = create_client(url, key)

        # --- OpenAI setup ---
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # ---------------------------------------------------------------------
    # 🔹 Main method
    # ---------------------------------------------------------------------
    def generate_message(self, registration_id: str, channel: str) -> Dict[str, Any]:
        """
        Pulls context for a given registration_id from Supabase and
        uses OpenAI to generate a contextual message.
        """

        logger.info(f"🎯 Generating {channel} message for registration_id={registration_id}")

        # 1️⃣ Pull context from Supabase
        context = self._fetch_context(registration_id)
        if not context:
            raise ValueError(f"No enrollment found for registration_id={registration_id}")

        # 2️⃣ Build prompt
        prompt = self._build_prompt(context, channel)

        # 3️⃣ Call OpenAI
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful admissions outreach assistant."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.8,
            max_tokens=250,
        )

        text = response.choices[0].message.content.strip()

        # 4️⃣ Build final message payload
        message = {
            "registration_id": registration_id,
            "channel": channel,
            "text": text,
            "tone": self._infer_tone(channel),
            "cta": self._generate_cta(channel),
            "timestamp": datetime.utcnow().isoformat(),
            "context": context,
        }

        # 5️⃣ Log for audit
        logger.info(f"✅ Message generated for {registration_id}: {text}")
        self._log_generation_event(registration_id, context["enrollment"].get("project_id", ""), channel, message_text=text)

        return message

    # ---------------------------------------------------------------------
    # 🔹 Helpers
    # ---------------------------------------------------------------------

    def _fetch_context(self, registration_id: str) -> Dict[str, Any]:
        """
        Retrieves relevant context from Supabase tables:
        - enrollment
        - leads
        - campaigns
        - lead_campaign_steps
        """

        # Enrollment
        enrollment = (
            self.supabase.table("enrollment")
            .select("*")
            .eq("registration_id", registration_id)
            .execute()
        )

        if not enrollment.data:
            return {}

        enrollment = enrollment.data[0]

        # Lead
        lead = (
            self.supabase.table("leads")
            .select("name,email,phone,interest,organization_id")
            .eq("id", enrollment["contact_id"])
            .execute()
        ).data
        lead = lead[0] if lead else {}

        # Campaign
        campaign = (
            self.supabase.table("campaigns")
            .select("name,description,is_active")
            .eq("id", enrollment["campaign_id"])
            .execute()
        ).data
        campaign = campaign[0] if campaign else {}

        # Step (latest)
        step = (
            self.supabase.table("lead_campaign_steps")
            .select("step_name,step_type,status")
            .eq("registration_id", registration_id)
            .order("step_order", desc=True)
            .limit(1)
            .execute()
        ).data
        step = step[0] if step else {}

        return {
            "lead": lead,
            "campaign": campaign,
            "step": step,
            "enrollment": enrollment,
        }

    def _build_prompt(self, context: Dict[str, Any], channel: str) -> str:
        """Builds a detailed context prompt for OpenAI."""
        lead = context.get("lead", {})
        campaign = context.get("campaign", {})
        step = context.get("step", {})
        enrollment = context.get("enrollment", {})

        name = lead.get("name", "Student")
        field = lead.get("interest", "your program of interest")
        campaign_name = campaign.get("name", "Admissions Outreach")
        step_name = step.get("step_name", "Intro Message")
        goal = enrollment.get("campaign_type", "encourage engagement")

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
            f"Write a short, personalized {channel} message to engage the student.\n"
            f"Keep it natural, friendly, and relevant to their interests.\n"
            f"Return only the message text."
        )

    def _infer_tone(self, channel: str) -> str:
        tones = {"sms": "friendly and concise", "email": "professional yet warm", "voice": "conversational and upbeat"}
        return tones.get(channel, "friendly")

    def _generate_cta(self, channel: str) -> str:
        ctas = {
            "sms": "Reply YES to schedule a quick chat!",
            "email": "Click below to schedule your consultation.",
            "voice": "Press 1 to connect with an advisor now.",
        }
        return ctas.get(channel, "Let’s connect soon!")

    def _log_generation_event(self, registration_id: str, project_id: str, channel: str, message_text: str):
        """
        Logs a message generation event in the event table.
        Ensures FK integrity by resolving registration_id -> enrollment.id
        """
        try:
            # ✅ Step 1: Resolve enrollment_id from registration_id
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

            # ✅ Step 2: Insert into event table
            event_data = {
                "project_id": project_id,
                "enrollment_id": enrollment_id,
                "event_type": "message_generated",
                "direction": "outbound",
                "payload": {
                    "channel": channel,
                    "message_preview": message_text[:120],
                },
                "created_at": datetime.utcnow().isoformat()
            }

            self.supabase.table("event").insert(event_data).execute()

        except Exception as e:
            logger.warning(f"Failed to log generation event: {e}")
