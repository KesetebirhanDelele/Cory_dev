import json, hmac, hashlib
from app.web.server import app
from fastapi.testclient import TestClient

client = TestClient(app)
SECRET = "dev-secret"

def sign_payload(body: dict) -> str:
    body_bytes = json.dumps(body).encode()
    mac = hmac.new(SECRET.encode(), body_bytes, hashlib.sha256)
    return mac.hexdigest()

def test_wa_webhook_happy_path():
    payload = {"provider_ref": "wa-001", "message": "Hello from WhatsApp!"}
    sig = sign_payload(payload)
    r = client.post("/webhooks/wa", json=payload, headers={"x-signature": sig})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "received"
    assert body["provider_ref"] == "wa-001"
    assert "data" in body

def test_wa_webhook_bad_signature():
    payload = {"provider_ref": "wa-bad", "message": "Bad HMAC"}
    r = client.post("/webhooks/wa", json=payload, headers={"x-signature": "invalid"})
    assert r.status_code == 401

def test_wa_webhook_duplicate_idempotency():
    payload = {"provider_ref": "wa-dupe", "message": "Repeat check"}
    sig = sign_payload(payload)

    r1 = client.post("/webhooks/wa", json=payload, headers={"x-signature": sig})
    assert r1.status_code == 200
    assert r1.json()["status"] == "received"

    r2 = client.post("/webhooks/wa", json=payload, headers={"x-signature": sig})
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"
