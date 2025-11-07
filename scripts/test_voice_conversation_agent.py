# scripts/test_voice_conversation_agent.py
"""
Simulated test for VoiceConversationAgent.
This test does not require Synthflow or ngrok.
"""

import os
import sys
import asyncio
from dotenv import load_dotenv

# --- Ensure root path and .env are loaded ---
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)
load_dotenv(os.path.join(ROOT_DIR, ".env"))

# --- Import after path setup ---
from app.agents.voice_conversation_agent import VoiceConversationAgent
from app.data.supabase_repo import SupabaseRepo


async def main():
    print("🚀 Starting simulated voice conversation test...\n")

    supabase = SupabaseRepo()
    agent = VoiceConversationAgent(supabase)

    result = await agent.start_call(
        org_id="org1",
        enrollment_id="enroll123",
        phone="+15551234567",
        lead_id="lead123",
        campaign_step_id="step456",
        simulate=True,  # ⚠️ No live call, uses fake transcript
    )

    print("\n🎯 Test Completed — Classification Result:")
    print(result)

    assert result["intent"] in [
        "ready_to_enroll",
        "interested_but_not_ready",
        "unsure_or_declined",
    ], f"Unexpected intent classification: {result['intent']}"

    print("\n✅ Simulation successful: valid intent detected.")


if __name__ == "__main__":
    asyncio.run(main())
