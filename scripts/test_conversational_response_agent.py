# scripts/test_conversational_response_agent.py
from app.agents.conversational_response_agent import ConversationalResponseAgent

if __name__ == "__main__":
    """
    Test run for the seeded enrollment using the correct registration_id.
    """

    # ✅ Must use a valid registration_id, not enrollment.id
    SEEDED_REGISTRATION_ID = "63db5123-02f6-4486-b11a-02bbc16fcc8f"

    agent = ConversationalResponseAgent()

    print(f"▶️ Processing conversation for registration_id={SEEDED_REGISTRATION_ID}")
    agent.process_conversation(SEEDED_REGISTRATION_ID)
    print("✅ Conversation processing complete.")
