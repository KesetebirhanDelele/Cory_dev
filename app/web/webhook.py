# app/web/webhook.py
from fastapi import APIRouter, Request, BackgroundTasks, Header, HTTPException
from typing import Optional
from datetime import datetime
import logging

from app.web.schemas import normalize_webhook_event

router = APIRouter()
logger = logging.getLogger("cory.webhook")


@router.get("/healthz")
async def healthz(request: Request):
    """
    Simple readiness/health endpoint used by tests & load balancers.
    Returns a timestamp and allows middleware to attach X-Request-Id.
    """
    # return the timestamp so the response body is not empty
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@router.post("/webhooks/campaign/{campaign_id}")
async def campaign_webhook(
    campaign_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    x_signature: Optional[str] = Header(None),
):
    """
    Minimal webhook handler that normalizes payloads and returns 422 on invalid payload.
    (Background processing is left as a placeholder.)
    """
    body = await request.json()
    try:
        event = normalize_webhook_event(body)
    except Exception as e:
        logger.warning("invalid webhook payload", extra={"error": str(e)})
        raise HTTPException(status_code=422, detail="invalid payload")

    # Example placeholder for scheduling processing:
    # background_tasks.add_task(process_event, campaign_id, event.model_dump())

    return {"status": "received", "campaign_id": campaign_id}

