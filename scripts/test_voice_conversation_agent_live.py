# scripts/test_voice_conversation_agent_live.py
"""
Integration Test — VoiceConversationAgent with Seeded Data

Simulates a realistic voice conversation flow using actual Supabase data.

Steps:
1️⃣ Fetch seeded enrollment, contact, and campaign from Supabase
2️⃣ Use ConversationalResponseAgent to interpret user’s spoken message
3️⃣ Simulate VoiceConversationAgent performing a call (or actual Synthflow call)
4️⃣ Persist transcript + AI intent + next_action back to Supabase
"""

import os
import sys
import asyncio
from datetime import datetime
from dotenv import load_dotenv
import httpx

# --- Bootstrap environment ---
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)
load_dotenv(os.path.join(ROOT_DIR, ".env"))

from app.agents.conversational_response_agent import ConversationalResponseAgent
from app.agents.voice_conversation_agent import VoiceConversationAgent
from app.agents.campaign_message_agent import CampaignMessageGeneratorAgent
from app.data.supabase_repo import SupabaseRepo, _cfg


# ✅ Replace with your seeded registration_id from Supabase
SEEDED_REGISTRATION_ID = "63db5123-02f6-4486-b11a-02bbc16fcc8f"


async def main():
    print("🎧 Starting live data voice simulation...\n")

    # --- Initialize repositories and agents ---
    supabase = SupabaseRepo()
    conv_agent = ConversationalResponseAgent()
    campaign_agent = CampaignMessageGeneratorAgent()
    voice_agent = VoiceConversationAgent(supabase)

    # --- Step 1: Fetch enrollment and related records ---
    print(f"🔍 Fetching enrollment for registration_id={SEEDED_REGISTRATION_ID}")
    url, key, schema = _cfg()

    async with httpx.AsyncClient() as client:
        enr_res = await client.get(
            f"{url}/rest/v1/enrollment?registration_id=eq.{SEEDED_REGISTRATION_ID}&select=id,contact_id,campaign_id,project_id",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
        )
        enr_res.raise_for_status()
        enrollment = enr_res.json()[0]

        contact_res = await client.get(
            f"{url}/rest/v1/contact?id=eq.{enrollment['contact_id']}&select=first_name,last_name,email,phone",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
        )
        contact_res.raise_for_status()
        contact = contact_res.json()[0]

        camp_res = await client.get(
            f"{url}/rest/v1/campaigns?id=eq.{enrollment['campaign_id']}&select=name,organization_id",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
        )
        camp_res.raise_for_status()
        campaign = camp_res.json()[0]

        step_res = await client.get(
            f"{url}/rest/v1/lead_campaign_steps?registration_id=eq.{SEEDED_REGISTRATION_ID}&select=id",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
        )

        if step_res.status_code == 400 or not step_res.json():
            print("⚠️ registration_id not found, trying enrollment_id instead...")
            step_res = await client.get(
                f"{url}/rest/v1/lead_campaign_steps?enrollment_id=eq.{enrollment['id']}&select=id",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )

        if step_res.status_code == 400:
            print("\n❌ Still failing (400 Bad Request). Dumping a sample row for inspection:")
            meta_res = await client.get(
                f"{url}/rest/v1/lead_campaign_steps?limit=1",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
            print("🧱 Sample row:", meta_res.json())
            raise RuntimeError("Unable to locate correct foreign key column for lead_campaign_steps.")

        step_res.raise_for_status()
        steps = step_res.json()
        if not steps:
            raise RuntimeError("No lead_campaign_steps found for this enrollment or registration.")
        campaign_step_id = steps[0]["id"]

    lead_name = f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip() or "there"
    phone = contact.get("phone")
    campaign_name = campaign.get("name", "Admissions Campaign")
    org_id = campaign.get("organization_id")
    enrollment_id = enrollment.get("id")

    print(f"📋 Campaign: {campaign_name}")
    print(f"👩‍🎓 Lead: {lead_name}, 📞 Phone: {phone}\n")

    # --- Step 2: Generate a campaign voice message ---
    print("🧠 Generating personalized campaign voice message...")
    generated_msg = campaign_agent.generate_message(SEEDED_REGISTRATION_ID, "voice")
    print(f"📤 Message Text: {generated_msg['message_text']}\n")

    # --- Step 3: Simulate lead response ---
    student_message = input("👩‍🎓 Simulated lead reply: ").strip() or "I'm still thinking about enrolling."

    # --- Step 4: Classify response via ConversationalResponseAgent ---
    classification = await conv_agent.classify_message(student_message)
    print("\n🤖 AI Classification Result:")
    print(classification)

    # --- Step 5: Simulate Voice Conversation (no real call by default) ---
    print("\n🎤 Simulating VoiceConversationAgent interaction...\n")
    result = await voice_agent.facilitate_call_from_campaign(
        generated_msg=generated_msg,
        enrollment_id=enrollment_id,
        lead_id=enrollment_id,
        phone=phone or "+15551234567",
        step_id=campaign_step_id,
        simulate=True,
    )

    # --- Step 6: Combine transcript + classification and persist ---
    transcript_text = (
        f"agent: {generated_msg['message_text']}\n"
        f"lead: {student_message}\n"
        f"ai: {result['response_message']}"
    )
    payload = {
        "intent": result["intent"],
        "next_action": result["next_action"],
        "transcript": transcript_text,
        "updated_at": datetime.utcnow().isoformat(),
    }

    async with httpx.AsyncClient() as client:
        patch_res = await client.patch(
            f"{url}/rest/v1/lead_campaign_steps?id=eq.{campaign_step_id}",
            json=payload,
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Prefer": "return=representation",
            },
        )
        patch_res.raise_for_status()

    print("\n💾 Results saved to Supabase (lead_campaign_steps).")
    print(f"\n📝 Transcript:\n{transcript_text}")
    print("\n✅ End of realistic voice session.\n")


if __name__ == "__main__":
    asyncio.run(main())
