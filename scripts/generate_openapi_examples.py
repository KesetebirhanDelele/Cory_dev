# scripts/generate_openapi_examples.py
import json
from app.web.schemas import WebhookEvent, EmailWebhookEvent, SmsWebhookEvent, VoiceWebhookEvent
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True), override=False)
examples = {
    "webhook_event": {
        "schema": WebhookEvent.model_json_schema(),
        "example": WebhookEvent.model_validate({
            "event":"lead_created",
            "channel":"webhook",
            "timestamp":"2025-10-06T12:00:00Z",
            "payload":{"first_name":"Alice","email":"a@example.com"}
        }).model_dump()
    },
    "email_event": {
        "schema": EmailWebhookEvent.model_json_schema(),
        "example": EmailWebhookEvent.model_validate({
            "event":"email_received",
            "channel":"email",
            "timestamp":"2025-10-06T12:00:00Z",
            "payload":{"to":"a@example.com","subject":"Hello"}
        }).model_dump()
    },
    "sms_event": {
        "schema": SmsWebhookEvent.model_json_schema(),
        "example": SmsWebhookEvent.model_validate({
            "event":"sms_reply",
            "channel":"sms",
            "timestamp":"2025-10-06T12:00:00Z",
            "payload":{"phone":"+15551234567","message":"Yes"}
        }).model_dump()
    }
}

with open("app/web/openapi_examples.json", "w") as f:
    json.dump(examples, f, indent=2, default=str)

print("✅ Wrote app/web/openapi_examples.json")

