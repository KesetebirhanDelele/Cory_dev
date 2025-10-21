import json, hmac, hashlib
from app.web.server import app
from fastapi.testclient import TestClient

client = TestClient(app)
SECRET = "dev-secret"

def sign_payload(body: dict) -> str:
    body_bytes = json.dumps(body).encode()
    mac = hmac.new(SECRET.encode(), body_bytes, hashlib.sha256)
    return mac.hexdigest()

def test_voice_webhook_happy_path():
    payload = {"provider_ref": "call-001", "status": "completed", "duration": 30}
    sig = sign_payload(payload)
    r = client.post("/webhooks/voice", json=payload, headers={"x-signature": sig})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "received"
    assert body["provider_ref"] == "call-001"
    assert "data" in body

def test_voice_webhook_bad_signature():
    payload = {"provider_ref": "call-bad", "status": "failed"}
    r = client.post("/webhooks/voice", json=payload, headers={"x-signature": "invalid"})
    assert r.status_code == 401

def test_voice_webhook_duplicate_idempotency():
    payload = {"provider_ref": "call-dupe", "status": "in-progress"}
    sig = sign_payload(payload)

    # First call → process
    r1 = client.post("/webhooks/voice", json=payload, headers={"x-signature": sig})
    assert r1.status_code == 200
    assert r1.json()["status"] == "received"

    # Duplicate → 200 but no reprocess
    r2 = client.post("/webhooks/voice", json=payload, headers={"x-signature": sig})
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"
