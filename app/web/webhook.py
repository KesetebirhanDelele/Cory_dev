# app/web/webhook.py
from fastapi import APIRouter, Request, BackgroundTasks, Header, HTTPException
from typing import Optional
from datetime import datetime
import logging

from app.web.schemas import normalize_webhook_event

# 👇 ADD: import your Supabase repo client
from app.repo.supabase_repo import SupabaseRepo

router = APIRouter()
logger = logging.getLogger("cory.webhook")

# 👇 ADD: instantiate a repo (ok to be module-level; uses env vars)
repo = SupabaseRepo()

# 👇 ADD: background task to refresh the MV (non-blocking)
async def _refresh_snapshot_bg():
    try:
        await repo.rpc("rpc_refresh_enrollment_state_snapshot", params={})
    except Exception as e:
        logger.warning("snapshot refresh rpc failed", extra={"error": str(e)})

@router.get("/healthz")
async def healthz(request: Request):
    """
    Simple readiness/health endpoint used by tests & load balancers.
    Returns a timestamp and allows middleware to attach X-Request-Id.
    """
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@router.post("/webhooks/campaign/{campaign_id}")
async def campaign_webhook(
    campaign_id: str,
    request: Request,
    background_tasks: BackgroundTasks,   # <- you already have this
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

    # TODO: persist the inbound event and/or write to dev_nexus.campaign_activity here

    # 👇 ADD: after successful processing (i.e., after DB commit), queue snapshot refresh
    background_tasks.add_task(_refresh_snapshot_bg)

    return {"status": "received", "campaign_id": campaign_id}
