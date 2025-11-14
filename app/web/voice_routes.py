# app/web/voice_routes.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.channels.providers.Voice.synthflow_adapter import send_voice_call
from app.web import storage

router = APIRouter()

class CallRequest(BaseModel):
    enrollment_id: str
    to: str
    org_id: str = "org-test"
    vars: dict | None = None

@router.post("/voice/call")
async def trigger_call(req: CallRequest):
    res = await send_voice_call(req.org_id, req.enrollment_id, req.to, vars=req.vars or {})
    # Save an initial outbound row if you want
    if res.get("provider_ref"):
        await storage.save_call_event({
            "call_id": res["provider_ref"],
            "timestamp": "", "speaker": "system",
            "text": f"initiated call, status={res['status']}",
            "raw": res.get("response_raw")
        })
    return res
