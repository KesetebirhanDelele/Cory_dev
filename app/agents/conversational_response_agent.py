import os
from dotenv import load_dotenv
import json
import logging
from datetime import datetime
from openai import OpenAI
from supabase import create_client, Client
import uuid

load_dotenv()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class ConversationalResponseAgent:
    """
    Handles inbound messages (SMS, Email, WhatsApp), classifies user intent,
    generates contextual replies, and logs conversation threads in Supabase.
    """

    def __init__(self):
        # Load Supabase credentials
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
        self.openai = OpenAI(api_key=api_key)  # ✅ rename for consistency

    # ------------------------------------------------------------------
    def process_conversation(self, registration_id: str):
        """
        Interactive mode:
        You simulate a student's messages in terminal.
        Each message triggers OpenAI for classification + response.
        Conversation is logged to Supabase in `message` + `event`.
        """
        # Fetch enrollment by registration_id
        enrollment_data = (
            self.supabase.table("enrollment")
            .select("id, contact_id, campaign_id, project_id")
            .eq("registration_id", registration_id)
            .execute()
        )

        if not enrollment_data.data:
            raise ValueError(
                f"Enrollment not found for registration_id={registration_id}"
            )
        enrollment = enrollment_data.data[0]

        # Fetch contact info
        contact = (
            self.supabase.table("contact")
            .select("id, first_name, last_name, email, phone")
            .eq("id", enrollment["contact_id"])
            .execute()
            .data[0]
        )

        contact_name = (
            f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip()
            or "there"
        )
        lead_name = contact_name

        # Fetch campaign
        campaign = (
            self.supabase.table("campaigns")
            .select("id, name, description")
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

            # Generate AI response
            response_json = self._generate_ai_reply(
                lead_name, student_message, campaign_name
            )

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

            # Log event
            self.supabase.table("event").insert({
                "id": str(uuid.uuid4()),
                "project_id": enrollment["project_id"],
                "enrollment_id": enrollment["id"],
                "event_type": "ai_conversational_response",
                "direction": "outbound",
                "payload": response_json
            }).execute()

            print(f"\n🤖 AI: {response_json['response_message']}\n")

    # ------------------------------------------------------------------
    def _generate_ai_reply(self, lead_name: str, inbound_text: str, campaign_name: str):
        """Internal helper to generate AI response"""
        prompt = f"""
        You are an admissions assistant for a campaign called "{campaign_name}".
        You are chatting with a student named {lead_name}.

        The student said: "{inbound_text}"

        Task:
        1️⃣ Classify the student's intent:
            - ready_to_enroll
            - interested_but_not_ready
            - unsure_or_declined
        2️⃣ Generate a short, empathetic response.
        3️⃣ Suggest the next system action:
            - schedule_followup_phone
            - send_information_packet
            - handoff_to_human

        Return **only valid JSON**:
        {{
          "intent": "<one of the 3 intents>",
          "response_message": "<natural response>",
          "next_action": "<one of the actions>"
        }}
        """

        try:
            ai_response = self.openai.chat.completions.create(  # ✅ correct API method
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a helpful admissions assistant."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
            )
            text = ai_response.choices[0].message.content.strip()
            response_json = json.loads(text)
        except Exception as e:
            logger.error(f"AI error: {e}")
            response_json = {
                "intent": "unsure_or_declined",
                "response_message": "Thanks for sharing! Would you like to learn more about our programs?",
                "next_action": "handoff_to_human"
            }
        return response_json
