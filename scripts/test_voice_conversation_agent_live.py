# scripts/test_voice_conversation_agent_live.py
"""
Integration Test — VoiceConversationAgent with Seeded Data (Live Call Version)

Runs a realistic voice conversation test using actual Supabase data.

Flow:
1️⃣ Fetch seeded enrollment, contact, and campaign data from Supabase
2️⃣ Generate a personalized campaign message (using OpenAI)
3️⃣ Trigger a real outbound call via Synthflow (through VoiceConversationAgent)
4️⃣ Wait for Synthflow to deliver the transcript to the webhook (/api/voice/transcript)
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

from app.agents.voice_conversation_agent import VoiceConversationAgent
from app.agents.campaign_message_agent import CampaignMessageGeneratorAgent
from app.data.supabase_repo import SupabaseRepo, _cfg

# ✅ Replace with your seeded registration_id from Supabase
SEEDED_REGISTRATION_ID = "63db5123-02f6-4486-b11a-02bbc16fcc8f"


async def main():
    print("🎧 Starting live data voice simulation...\n")

    # --- Initialize repositories and agents ---
    supabase = SupabaseRepo()
    campaign_agent = CampaignMessageGeneratorAgent()
    voice_agent = VoiceConversationAgent(supabase)

    # --- Step 1: Fetch enrollment and related records ---
    print(f"🔍 Fetching enrollment for registration_id={SEEDED_REGISTRATION_ID}")
    url, key, schema = _cfg()

    async with httpx.AsyncClient() as client:
        enr_res = await client.get(
            f"{url}/rest/v1/enrollment?registration_id=eq.{SEEDED_REGISTRATION_ID}"
            "&select=id,contact_id,campaign_id,project_id",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
        )
        enr_res.raise_for_status()
        enrollment = enr_res.json()[0]

        contact_res = await client.get(
            f"{url}/rest/v1/contact?id=eq.{enrollment['contact_id']}"
            "&select=first_name,last_name,email,phone",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
        )
        contact_res.raise_for_status()
        contact = contact_res.json()[0]

        camp_res = await client.get(
            f"{url}/rest/v1/campaigns?id=eq.{enrollment['campaign_id']}"
            "&select=name,organization_id",
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

        step_res.raise_for_status()
        steps = step_res.json()
        if not steps:
            raise RuntimeError(
                "No lead_campaign_steps found for this enrollment or registration."
            )
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

    # --- Step 3: Initiate real outbound voice call via Synthflow ---
    print("📞 Initiating real voice call via Synthflow...\n")

    result = await voice_agent.facilitate_call_from_campaign(
        generated_msg=generated_msg,
        enrollment_id=enrollment_id,
        lead_id=enrollment_id,
        phone=phone,
        step_id=campaign_step_id,
        simulate=False,  # ensures a real Synthflow API call
    )

    print("✅ Outbound call initiated successfully.")
    print(f"   → Provider Ref: {result.get('provider_ref')}")
    print(f"   → Status: {result.get('status')}\n")

    print("🕒 Waiting for Synthflow to post transcript to webhook (/api/voice/transcript)...\n")
    print("   Use ngrok logs or your FastAPI console to verify incoming webhook calls.")
    print("   Once the transcript is received, it will automatically be stored in Supabase.\n")

    # Optional: short polling loop to check if webhook has posted transcript yet
    for attempt in range(10):
        await asyncio.sleep(15)
        print(f"⏳ Checking for transcript in Supabase (attempt {attempt + 1}/10)...")

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{url}/rest/v1/message?provider_ref=eq.{result.get('provider_ref')}&select=content,transcript,status",
                    headers={"apikey": key, "Authorization": f"Bearer {key}"},
                )
                if resp.status_code == 200 and resp.json():
                    print("🎤 Transcript received via webhook:")
                    print(resp.json())
                    break
        except Exception as e:
            print(f"⚠️ Polling attempt failed: {e}")

    print("\n✅ End of live voice session.\n")


if __name__ == "__main__":
    asyncio.run(main())
