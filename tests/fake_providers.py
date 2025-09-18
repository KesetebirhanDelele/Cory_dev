import time, uuid, os

def sms_send(to: str, body: str, **kwargs):
    assert os.getenv("SIMULATE_PROVIDERS") == "true"
    return {"status": "queued", "provider": "sms-sim", "id": f"sms_{uuid.uuid4().hex}", "to": to, "body": body}

def email_send(to: str, subject: str, html: str, **kwargs):
    assert os.getenv("SIMULATE_PROVIDERS") == "true"
    return {"status": "queued", "provider": "email-sim", "id": f"em_{uuid.uuid4().hex}", "to": to, "subject": subject}

def voice_place_call(to: str, script: str, **kwargs):
    assert os.getenv("SIMULATE_PROVIDERS") == "true"
    # emulate short call; your call_processing_agent will later read a staging record or policy
    return {"status": "queued", "provider": "voice-sim", "id": f"call_{uuid.uuid4().hex}", "to": to, "script": script, "duration_sec": 12, "result": "no_answer"}
