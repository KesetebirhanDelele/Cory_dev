# providers/voice.py
import uuid

# TODO: replace with Synthflow/Twilio/Switchboard call
async def place_call(to_number: str, from_number: str, metadata: dict) -> str:
    # Return provider's call id
    return f"mock-call-{uuid.uuid4()}"
