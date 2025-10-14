# app/web/webhook.py
from fastapi import APIRouter, Request, BackgroundTasks, Header, HTTPException
from typing import Optional
from datetime import datetime
import logging
from app.web.schemas import normalize_webhook_event
from app.orchestrator.temporal.signal_bridge import send_temporal_signal  # ✅ new import

router = APIRouter()
logger = logging.getLogger("cory.webhook")


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

    # --- Extract fields ---
    provider_ref = None
    workflow_id = None

    # Try normalized payload first
    if isinstance(event.payload, dict):
        provider_ref = event.payload.get("provider_ref") or event.payload.get("providerRef")
        workflow_id = event.payload.get("workflow_id") or event.payload.get("workflowId")

    # Try metadata fallback
    if not provider_ref and isinstance(event.metadata, dict):
        provider_ref = event.metadata.get("provider_ref")

    # Try raw body fallback
    if not workflow_id and isinstance(body, dict):
        if "payload" in body and isinstance(body["payload"], dict):
            workflow_id = body["payload"].get("workflow_id") or body["payload"].get("workflowId")

    # --- Idempotency check ---
    if provider_ref:
        should_process = await request.app.state.idempotency.reserve(provider_ref)
        if not should_process:
            logger.info("duplicate webhook - skipping processing", extra={"provider_ref": provider_ref})
            return {"status": "duplicate", "provider_ref": provider_ref}

    # --- Temporal Signal Bridge call ---
    try:
        from app.orchestrator.temporal.signal_bridge import send_temporal_signal
        if workflow_id:
            await send_temporal_signal(workflow_id, event.dict())
    except Exception as e:
        logger.warning("failed to send temporal signal", extra={"error": str(e)})

        # --- NEW: Log inbound event to Supabase ---
    try:
        from app.data import supabase_repo
        await supabase_repo.log_inbound(provider_ref, event.event, body)
    except Exception as e:
        logger.warning("failed to log inbound event", extra={"error": str(e)})

    # --- Continue downstream ---
    await request.app.state.process_event_fn(campaign_id, event)

    return {"status": "received", "campaign_id": campaign_id}
