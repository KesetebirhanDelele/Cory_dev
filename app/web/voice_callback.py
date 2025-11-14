# app/web/voice_callback.py
from fastapi import APIRouter, Request, HTTPException
from datetime import datetime
import logging
import json
from app.web import storage  # we'll create a simple storage helper next

router = APIRouter()
log = logging.getLogger("cory.voice.callback")

@router.post("/voice/callback")
async def synthflow_callback(request: Request):
    """
    Receives POSTs from Synthflow with call events (transcript, speaker, timestamps).
    Persist them for later inspection.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")

    # Example payload shapes differ. Log it and attempt to parse sensible fields.
    log.info("Synthflow callback received", extra={"payload": payload})

    # Extract call_id, events/transcript — adjust to actual payload shape from Synthflow
    call_id = payload.get("call_id") or payload.get("id") or payload.get("call") or payload.get("session_id")
    events = payload.get("events") or payload.get("transcripts") or [payload]

    # normalize into rows: each row -> call_id, timestamp, speaker, text
    rows = []
    now = datetime.utcnow().isoformat()
    if isinstance(events, list):
        for ev in events:
            speaker = ev.get("speaker") or ev.get("role") or ev.get("who")
            text = ev.get("text") or ev.get("utterance") or json.dumps(ev)
            ts = ev.get("timestamp") or ev.get("time") or now
            rows.append({"call_id": call_id, "timestamp": ts, "speaker": speaker, "text": text, "raw": ev})
    else:
        rows.append({"call_id": call_id, "timestamp": now, "speaker": None, "text": json.dumps(events), "raw": events})

    # persist rows
    for r in rows:
        await storage.save_call_event(r)

    return {"ok": True, "saved": len(rows)}
