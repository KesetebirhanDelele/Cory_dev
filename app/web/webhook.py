# webhook.py
from fastapi import FastAPI, Request
from db import upsert_staging
import uvicorn

app = FastAPI()

@app.post("/voice/webhook")
async def voice_hook(req: Request):
    payload = await req.json()
    # map provider fields -> staging schema
    row = {
        "enrollment_id": payload.get("enrollment_id"),
        "contact_id": payload.get("contact_id"),
        "campaign_id": payload.get("campaign_id"),
        "type_of_call": payload.get("type_of_call"),
        "call_id": payload.get("call_id"),
        "module_id": payload.get("module_id"),
        "duration_seconds": payload.get("duration"),
        "end_call_reason": payload.get("end_call_reason"),
        "executed_actions": payload.get("executed_actions"),
        "prompt_variables": payload.get("prompt_variables"),
        "recording_url": payload.get("recording_url"),
        "transcript": payload.get("transcript"),
        "start_time_epoch_ms": payload.get("start_time_ms"),
        "agent": payload.get("agent"),
        "timezone": payload.get("timezone"),
        "phone_number_to": payload.get("to"),
        "phone_number_from": payload.get("from"),
        "status": payload.get("status"),
        "campaign_type": payload.get("campaign_type"),
        "classification": payload.get("classification"),
        "appointment_time": payload.get("appointment_time")
    }
    await upsert_staging(row)
    return {"ok": True}
