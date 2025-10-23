# tests/web/test_webhook_replay.py
import time
import hmac
import hashlib
from fastapi.testclient import TestClient
from app.web.server import app

client = TestClient(app)

# ✅ Matches app’s format
def make_sig(ts, nonce, body):
    secret = "dev-secret-key"
    message = f"{ts}.{nonce}.".encode() + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()

# ✅ Valid JSON that passes model validation
VALID_BODY = b'{"event": "test", "channel": "webhook", "timestamp": "2025-10-09T00:00:00Z", "payload": {}}'


def test_valid_signature():
    ts = str(int(time.time()))
    nonce = "abc123"
    sig = make_sig(ts, nonce, VALID_BODY)
    r = client.post(
        "/webhooks/campaign/test",
        headers={
            "X-Signature": sig,
            "X-Timestamp": ts,
            "X-Nonce": nonce,
        },
        content=VALID_BODY,
    )
    assert r.status_code == 200


def test_old_timestamp_rejected():
    ts = str(int(time.time()) - 600)
    nonce = "old123"
    sig = make_sig(ts, nonce, VALID_BODY)
    r = client.post(
        "/webhooks/campaign/test",
        headers={
            "X-Signature": sig,
            "X-Timestamp": ts,
            "X-Nonce": nonce,
        },
        content=VALID_BODY,
    )
    assert r.status_code == 401


def test_replay_rejected():
    ts = str(int(time.time()))
    nonce = "replay123"
    sig = make_sig(ts, nonce, VALID_BODY)
    headers = {
        "X-Signature": sig,
        "X-Timestamp": ts,
        "X-Nonce": nonce,
    }
    # First call passes
    r1 = client.post("/webhooks/campaign/test", headers=headers, content=VALID_BODY)
    assert r1.status_code == 200

    # Replay rejected
    r2 = client.post("/webhooks/campaign/test", headers=headers, content=VALID_BODY)
    assert r2.status_code == 401
