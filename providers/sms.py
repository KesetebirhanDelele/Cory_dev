import uuid
from typing import Optional

# Replace this stub with your real SlickText/Twilio call.
# Keep the signature your sms_sender expects.
async def send_sms(org_id: str, enrollment_id: str, body: str, *, to: Optional[str] = None) -> str:
    # TODO: look up "to" from DB if not provided
    # TODO: call your SMS provider and return their message id
    return f"mock-sms-{uuid.uuid4()}"
