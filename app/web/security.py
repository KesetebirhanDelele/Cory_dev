# app/web/security.py
import hmac
import hashlib
import os
import time
from fastapi import HTTPException

# 🔐 Shared secret (rotated in real environments)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "dev-secret-key")
# print(f"[DEBUG] Using WEBHOOK_SECRET={WEBHOOK_SECRET!r}")

# 🧠 Simple in-memory nonce cache for replay protection
USED_NONCES = {}
MAX_SKEW_SECONDS = 300  # 5 minutes


def verify_request_signature(timestamp: str, nonce: str, signature: str, body: bytes) -> None:
    """Validate HMAC signature, timestamp skew, and replay nonce."""
    now = time.time()
    try:
        ts = float(timestamp)
    except ValueError:
        raise HTTPException(status_code=401, detail="invalid timestamp")

    # ⏱️ Check if the timestamp is within the allowed skew window
    if abs(now - ts) > MAX_SKEW_SECONDS:
        raise HTTPException(status_code=401, detail="timestamp outside valid window")

    # 🔁 Check if the nonce was already used (prevent replay)
    if nonce in USED_NONCES:
        raise HTTPException(status_code=401, detail="nonce already used")
    USED_NONCES[nonce] = ts

    # 🧾 Build the message exactly like the tests do
    message = f"{timestamp}.{nonce}.{body.decode()}".encode()
    expected_sig = hmac.new(WEBHOOK_SECRET.encode(), message, hashlib.sha256).hexdigest()

    # ✅ Compare securely
    if not hmac.compare_digest(expected_sig, signature):
        print({
            "expected_sig": expected_sig,
            "provided_sig": signature,
            "message": message,
        })
        raise HTTPException(status_code=401, detail="invalid signature")
