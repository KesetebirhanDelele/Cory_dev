# app/web/server.py
from fastapi import FastAPI
from datetime import datetime, timezone
import asyncio

from app.web.middleware import setup_middleware
from app.web.webhook import router as webhook_router
from app.web.idempotency_cache import IdempotencyCache
from app.web.sms_webhook import router as sms_router
from app.web.email_webhook import router as email_router
from app.web.voice_webhook import router as voice_router
from app.web.wa_webhook import router as wa_router

app = FastAPI(title="Cory Admissions API")
app.include_router(sms_router)
app.include_router(email_router)
app.include_router(voice_router)
app.include_router(wa_router)

# ✅ Initialize idempotency cache and stub functions
idempotency_cache = IdempotencyCache(ttl_seconds=300)
app.state.idempotency = idempotency_cache
app.state.processed_refs = idempotency_cache


async def dummy_process_event_fn(campaign_id, event):
    await asyncio.sleep(0)
    return {"ok": True, "campaign_id": campaign_id, "event": event.event}

app.state.process_event_fn = dummy_process_event_fn

# Attach middleware
setup_middleware(app)

@app.get("/healthz")
def healthz():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

app.include_router(webhook_router, prefix="/webhooks")
