# app/web/webhook.py
from fastapi import APIRouter, Request, BackgroundTasks, Header, HTTPException
from typing import Optional
from datetime import datetime
import logging

from app.web.schemas import normalize_webhook_event
from app.web.security import verify_request_signature
from app.repo.supabase_repo import SupabaseRepo
from app.orchestrator.temporal.signal_bridge import send_temporal_signal

router = APIRouter()
logger = logging.getLogger("cory.webhook")
repo = SupabaseRepo()


# Background refresh task
async def _refresh_snapshot_bg():
    try:
        await repo.rpc("rpc_refresh_enrollment_state_snapshot", params={})
    except Exception as e:
        logger.warning("snapshot refresh rpc failed", extra={"error": str(e)})


@router.get("/healthz")
async def healthz(request: Request):
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@router.post("/webhooks/campaign/{campaign_id}")
async def campaign_webhook(
    campaign_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
):
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

    # Trigger snapshot refresh (non-blocking)
    background_tasks.add_task(_refresh_snapshot_bg)

    return {"status": "received", "campaign_id": campaign_id}
