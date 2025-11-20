# app/web/webhook.py
from fastapi import APIRouter, Request, BackgroundTasks, HTTPException
from typing import Optional
from datetime import datetime
import logging

from app.web.schemas import normalize_webhook_event
from app.web.security import verify_request_signature
from app.repo.supabase_repo import SupabaseRepo
from app.orchestrator.temporal.signal_bridge import send_temporal_signal
from app.web import metrics as metrics_mod

router = APIRouter()
logger = logging.getLogger("cory.webhook")
repo = SupabaseRepo()


# Background refresh task
async def _refresh_snapshot_bg() -> None:
    """Kick off a non-blocking refresh of enrollment_state_snapshot."""
    try:
        await repo.rpc("rpc_refresh_enrollment_state_snapshot", params={})
    except Exception as e:
        logger.warning(
            "snapshot refresh rpc failed",
            extra={"error": str(e)},
        )


@router.get("/healthz")
async def healthz(request: Request):
    """Simple health check endpoint."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@router.post("/webhooks/campaign/{campaign_id}")
async def campaign_webhook(
    campaign_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Generic campaign provider webhook.

    Responsibilities:
    - Verify HMAC-style signature headers
    - Normalize payload into an internal WebhookEvent via normalize_webhook_event
    - Enforce idempotency using app.state.processed_refs
    - Trigger a background refresh of enrollment_state_snapshot

    Note:
    This endpoint does *not* currently bridge into the ProviderEvent / CampaignWorkflow
    intent pipeline; SMS/Email/Voice-specific webhooks handle that path.
    """
    # 🔒 Security check — timestamp, nonce, and signature
    x_signature = request.headers.get("X-Signature")
    x_timestamp = request.headers.get("X-Timestamp")
    x_nonce = request.headers.get("X-Nonce")

    if not all([x_signature, x_timestamp, x_nonce]):
        raise HTTPException(status_code=401, detail="missing security headers")

    body_bytes = await request.body()
    verify_request_signature(x_timestamp, x_nonce, x_signature, body_bytes)

    # ✅ Parse and normalize
    body = await request.json()
    try:
        event = normalize_webhook_event(body)
    except Exception as e:
        logger.warning("invalid webhook payload", extra={"error": str(e)})
        raise HTTPException(status_code=422, detail="invalid payload")

    # ✅ Idempotency check (avoid reprocessing duplicates)
    ref = getattr(event, "provider_ref", None) or getattr(event, "id", None)
    if not ref:
        raise HTTPException(status_code=400, detail="missing event reference")

    cache = request.app.state.processed_refs
    if ref in cache:
        logger.info("Duplicate webhook ignored", extra={"ref": ref})
        metrics_mod.IDEMPOTENT_HITS.inc()  # ✅ increment metric for duplicates
        return {"status": "duplicate"}

    cache.set(ref, True)  # store it for future duplicate detection

    # Trigger snapshot refresh (non-blocking)
    background_tasks.add_task(_refresh_snapshot_bg)

    # Optional logging of any intent-like fields that providers might send
    intent = getattr(event, "intent", None) or getattr(event, "status", None)
    logger.info(
        "✅ Campaign webhook received",
        extra={"campaign_id": campaign_id, "ref": ref, "intent_or_status": intent},
    )

    return {"status": "received", "campaign_id": campaign_id}
