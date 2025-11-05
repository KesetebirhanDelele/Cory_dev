from app.agents.campaign_message_agent import CampaignMessageGeneratorAgent

agent = CampaignMessageGeneratorAgent()
result = agent.generate_message(
    registration_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    channel="sms"
)

print(result["text"])
