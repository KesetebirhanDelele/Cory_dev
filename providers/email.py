# providers/email.py
import os, uuid

PROVIDER_MODE  = os.getenv("PROVIDER_MODE", "mock").lower()
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "mock").lower()

def send_email(to_email: str, subject: str, body: str) -> str:
    # dev/mock default
    if PROVIDER_MODE == "mock" or EMAIL_PROVIDER == "mock":
        return f"mock-email:{to_email}:{uuid.uuid4().hex[:8]}"
    # TODO: plug Mandrill/SendGrid here (return their message ID)
    raise RuntimeError("Real email provider not configured. Set EMAIL_PROVIDER=mandrill/sendgrid and implement calls.")
