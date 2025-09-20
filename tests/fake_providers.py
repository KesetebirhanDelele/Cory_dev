import uuid, os

def _require_sim():
    if os.getenv("SIMULATE_PROVIDERS") != "true":
        raise RuntimeError("SIMULATE_PROVIDERS must be 'true' for fake providers")

def sms_send(to: str, body: str, **kwargs):
    _require_sim()
    return {
        "status": "queued",
        "provider": "sms-sim",
        "provider_id": f"sms_{uuid.uuid4().hex}",
        "to": to,
        "body": body,
    }

def email_send(to: str, subject: str, html: str, **kwargs):
    _require_sim()
    return {
        "status": "queued",
        "provider": "email-sim",
        "provider_id": f"em_{uuid.uuid4().hex}",
        "to": to,
        "subject": subject,
        "html": html,
    }

def voice_place_call(to: str, script: str, **kwargs):
    _require_sim()
    return {
        "status": "queued",
        "provider": "voice-sim",
        "provider_id": f"call_{uuid.uuid4().hex}",
        "to": to,
        "script": script,
        "duration_sec": 12,
        "result": "no_answer",
    }
