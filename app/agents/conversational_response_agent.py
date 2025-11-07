# app/agents/conversational_response_agent.py
"""
ConversationalResponseAgent
----------------------------------------------------------
- Classifies message intent (ready_to_enroll, interested_but_not_ready, unsure_or_declined)
- Generates empathetic, contextual replies
- Logs conversations and AI responses in Supabase
- Provides classify_message() for VoiceConversationAgent and workflows
- Can respond directly to generated campaign messages
"""

import os
import json
import uuid
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from openai import OpenAI
from supabase import create_client, Client

# ---------------------------------------------------------------------
# 🔧 Environment & Logging Setup
# ---------------------------------------------------------------------
load_dotenv()
logger = logging.getLogger("cory.conversational.agent")
logger.setLevel(logging.INFO)


class ConversationalResponseAgent:
    """
    Handles inbound/outbound message conversations across channels
    (SMS, Email, WhatsApp, Voice), performs classification, and
    returns structured response objects for automation workflows.
    """

    def __init__(self):
        # --- Supabase setup ---
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise ValueError("Missing Supabase credentials (SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY).")

        self.supabase: Client = create_client(url, key)

        # --- OpenAI setup ---
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("Missing OPENAI_API_KEY in environment variables.")
        self.openai = OpenAI(api_key=api_key)

    # ------------------------------------------------------------------
    # 🧠 AI Response Generation Core
    # ------------------------------------------------------------------
    def _generate_ai_reply(self, lead_name: str, inbound_text: str, campaign_name: str) -> dict:
        """
        Internal helper for OpenAI-based classification and response generation.
        """
        prompt = f"""
        You are an admissions assistant for a campaign called "{campaign_name}".
        You are chatting with a student named {lead_name}.

        The student said: "{inbound_text}"

        Your task:
        1️⃣ Classify the student's intent:
            - ready_to_enroll
            - interested_but_not_ready
            - unsure_or_declined

        2️⃣ Generate a short, empathetic, human-like response (1-2 sentences).

        3️⃣ Suggest the next system action:
            - schedule_followup_phone
            - send_information_packet
            - handoff_to_human

        Return ONLY valid JSON in the following format:
        {{
          "intent": "<one of the 3 intents>",
          "response_message": "<natural empathetic message>",
          "next_action": "<one of the actions>"
        }}
        """

        try:
            ai_response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a warm and helpful admissions assistant."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=250,
            )
            text = ai_response.choices[0].message.content.strip()

            # Try parsing JSON from model output
            try:
                response_json = json.loads(text)
            except json.JSONDecodeError:
                logger.warning(f"⚠️ Failed to parse AI JSON: {text}")
                response_json = {
                    "intent": "unsure_or_declined",
                    "response_message": text,
                    "next_action": "handoff_to_human",
                }

        except Exception as e:
            logger.error(f"AI error during response generation: {e}")
            response_json = {
                "intent": "unsure_or_declined",
                "response_message": "Thanks for sharing! Would you like to learn more about our programs?",
                "next_action": "handoff_to_human",
            }

        return response_json

    # ------------------------------------------------------------------
    # 💬 Conversation Simulation (Manual)
    # ------------------------------------------------------------------
    def process_conversation(self, registration_id: str):
        """
        Manual test mode for SMS/email-like conversations.
        Fetches enrollment context and allows simulated dialogue in the terminal.
        """

        enrollment_data = (
            self.supabase.table("enrollment")
            .select("id, contact_id, campaign_id, project_id")
            .eq("registration_id", registration_id)
            .execute()
        )

        if not enrollment_data.data:
            raise ValueError(f"Enrollment not found for registration_id={registration_id}")

        enrollment = enrollment_data.data[0]
        contact = (
            self.supabase.table("contact")
            .select("first_name, last_name, email, phone")
            .eq("id", enrollment["contact_id"])
            .execute()
            .data[0]
        )

        lead_name = (f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip()) or "there"
        campaign = (
            self.supabase.table("campaigns")
            .select("id, name")
            .eq("id", enrollment["campaign_id"])
            .execute()
            .data[0]
        )
        campaign_name = campaign.get("name", "Admissions Campaign")

        print(f"\n🎓 Connected to campaign: {campaign_name}")
        print(f"💬 Chatting with simulated lead: {lead_name}\n")

        while True:
            student_message = input("👩‍🎓 Student: ").strip()
            if student_message.lower() in {"exit", "quit"}:
                print("👋 Ending conversation.")
                break

            # Log inbound message
            inbound_msg = {
                "id": str(uuid.uuid4()),
                "project_id": enrollment["project_id"],
                "enrollment_id": enrollment["id"],
                "channel": "sms",
                "direction": "inbound",
                "content": {"text": student_message},
                "status": "received",
                "occurred_at": datetime.utcnow().isoformat(),
            }
            self.supabase.table("message").insert(inbound_msg).execute()

            # AI classify + respond
            response_json = self._generate_ai_reply(lead_name, student_message, campaign_name)

            # Log outbound message
            outbound_msg = {
                "id": str(uuid.uuid4()),
                "project_id": enrollment["project_id"],
                "enrollment_id": enrollment["id"],
                "channel": "sms",
                "direction": "outbound",
                "content": {"text": response_json["response_message"]},
                "status": "sent",
                "occurred_at": datetime.utcnow().isoformat(),
            }
            self.supabase.table("message").insert(outbound_msg).execute()

            # Log AI event
            self.supabase.table("event").insert({
                "id": str(uuid.uuid4()),
                "project_id": enrollment["project_id"],
                "enrollment_id": enrollment["id"],
                "event_type": "ai_conversational_response",
                "direction": "outbound",
                "payload": response_json,
                "created_at": datetime.utcnow().isoformat(),
            }).execute()

            print(f"\n🤖 AI: {response_json['response_message']}\n")

    # ------------------------------------------------------------------
    # 🧩 Respond to Campaign Message
    # ------------------------------------------------------------------
    async def respond_to_generated_message(
        self,
        generated_msg: Dict[str, Any],
        simulated_reply: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Handles a real or simulated user reply to a campaign-generated message.
        Can be invoked by Temporal workflows or test harnesses.

        Args:
            generated_msg: message payload returned from CampaignMessageGeneratorAgent
            simulated_reply: user reply text (optional, prompts input if missing)
        Returns:
            dict: AI classification + response_message + next_action
        """
        lead_name = generated_msg["context"]["lead"].get("name", "Student")
        campaign_name = generated_msg["context"]["campaign"].get("name", "Admissions Campaign")
        outbound_text = generated_msg["message_text"]

        print(f"\n📤 Outbound Message Sent: {outbound_text}")

        if not simulated_reply:
            simulated_reply = input("👩‍🎓 Lead Reply: ").strip()
        if not simulated_reply:
            simulated_reply = "I'm still thinking about it."

        classification = self._generate_ai_reply(lead_name, simulated_reply, campaign_name)

        print(f"\n🤖 AI: {classification['response_message']}")
        logger.info(f"Intent={classification['intent']}, NextAction={classification['next_action']}")

        return classification

    # ------------------------------------------------------------------
    # 🔍 Lightweight API (used by VoiceConversationAgent)
    # ------------------------------------------------------------------
    async def classify_message(self, text: str) -> dict:
        """
        Classify free-form text (e.g., call transcript) into intent and next_action.
        Used by VoiceConversationAgent and automated workflows.
        """
        result = self._generate_ai_reply("Voice Lead", text, "Admissions Campaign")
        return {
            "intent": result.get("intent"),
            "response_message": result.get("response_message"),
            "next_action": result.get("next_action"),
        }
