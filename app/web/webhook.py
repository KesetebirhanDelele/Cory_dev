# app/web/webhook.py (excerpt)
from fastapi import APIRouter, Request, BackgroundTasks, Header, HTTPException
from typing import Optional
from datetime import datetime
import logging

from app.web.schemas import normalize_webhook_event

router = APIRouter()
logger = logging.getLogger("cory.webhook")

#@router.post("/webhooks/campaign/{campaign_id}")
# ✅ correct
@router.post("/campaign/{campaign_id}")

async def campaign_webhook(
    campaign_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    x_signature: Optional[str] = Header(None),
):
    body = await request.json()
    try:
        event = normalize_webhook_event(body)
    except Exception as e:
        logger.warning("invalid webhook payload", extra={"error": str(e)})
        raise HTTPException(status_code=422, detail="invalid payload")

    # Extract provider_ref from payload or metadata
    provider_ref = None
    if isinstance(event.payload, dict):
        provider_ref = event.payload.get("provider_ref") or event.payload.get("providerRef")
    if not provider_ref and isinstance(event.metadata, dict):
        provider_ref = event.metadata.get("provider_ref")

    # If we have provider_ref, consult idempotency cache
    if provider_ref:
        should_process = await request.app.state.idempotency.reserve(provider_ref)
        if not should_process:
            logger.info("duplicate webhook - skipping processing", extra={"provider_ref": provider_ref})
            # Accept but skip downstream processing
            return {"status": "duplicate", "provider_ref": provider_ref}

    # Process: use app.state.process_event_fn (testable)
    await request.app.state.process_event_fn(campaign_id, event)

    return {"status": "received", "campaign_id": campaign_id}
