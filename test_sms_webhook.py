import requests
import json
import time
import uuid
import hmac
import hashlib
import os

SECRET = os.getenv("SMS_WEBHOOK_SECRET", "super-secret-hmac-key")

URL = "http://127.0.0.1:8000/webhooks/sms"

# --- Body (exactly the SlickText example) ---
body = {
    "messageId": "4c2c7fb1-e7cc-489b-a45e-2379fe9a7b55",
    "message": "Hello, I have a question about my appointment",
    "fromNumber": "+157155502123",
    "toNumber": "+18885551234",
    "keyword": "CORY",
    "timestamp": "2025-01-15T17:44:12Z"
}

# Convert to EXACT JSON with no pretty formatting
body_str = json.dumps(body, separators=(",", ":"))

timestamp = str(time.time())
nonce = uuid.uuid4().hex

message = f"{timestamp}.{nonce}.{body_str}".encode()
signature = hmac.new(SECRET.encode(), message, hashlib.sha256).hexdigest()

headers = {
    "Content-Type": "application/json",
    "x-timestamp": timestamp,
    "x-nonce": nonce,
    "x-signature": signature,
}

print("=== Sending Request ===")
print("Headers:", headers)
print("Body:", body_str)

response = requests.post(URL, data=body_str.encode(), headers=headers)

print("\n=== Response ===")
print("Status:", response.status_code)
print("Body:", response.text)
