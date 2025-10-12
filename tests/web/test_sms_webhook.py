import json, hmac, hashlib
from app.web.server import app
from fastapi.testclient import TestClient

client = TestClient(app)
SECRET = "super-secret-hmac-key"

def make_sig(body: dict):
    body_bytes = json.dumps(body).encode()
    mac = hmac.new(SECRET.encode(), body_bytes, hashlib.sha256)
    return mac.hexdigest()

def test_sms_webhook_valid_signature():
    payload = {"message_id": "abc123", "text": "Hello"}
    sig = make_sig(payload)
    r = client.post("/webhooks/sms", json=payload, headers={"x-signature": sig})
    assert r.status_code == 200
    assert r.json()["status"] in ["received", "duplicate"]

def test_sms_webhook_bad_signature():
    payload = {"message_id": "xyz999", "text": "Bad sig"}
    r = client.post("/webhooks/sms", json=payload, headers={"x-signature": "invalid"})
    assert r.status_code == 401

def test_sms_webhook_duplicate_noop():
    payload = {"message_id": "dup-001", "text": "Repeat"}
    sig = make_sig(payload)

    # First call - should process
    r1 = client.post("/webhooks/sms", json=payload, headers={"x-signature": sig})
    assert r1.status_code == 200

    # Second call - should be duplicate
    r2 = client.post("/webhooks/sms", json=payload, headers={"x-signature": sig})
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"
