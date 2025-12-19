# app/web/debug_sms.py

from fastapi import APIRouter, Request
import logging

router = APIRouter()
log = logging.getLogger("cory.debug_sms")


@router.post("/debug/sms")
async def debug_sms(request: Request):
    """
    Minimal debug endpoint to see exactly what the server receives.
    """

    raw = await request.body()
    text = raw.decode("utf-8", errors="ignore")

    try:
        form = await request.form()
        data = dict(form)
    except Exception:
        data = None

    log.info("[DEBUG SMS] raw_body=%r parsed_form=%s", text, data)

    return {
        "ok": True,
        "raw_body": text,
        "parsed_form": data,
    }
