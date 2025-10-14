# app/web/server.py
from fastapi import FastAPI
from datetime import datetime, timezone

from app.web.middleware import setup_middleware
from app.web.webhook import router as webhook_router
from app.web.idempotency_cache import IdempotencyCache
from app.web.sms_webhook import router as sms_router
from app.web.email_webhook import router as email_router
from app.web.voice_webhook import router as voice_router
from app.web.wa_webhook import router as wa_router

# ✅ import the Temporal bridge
from app.orchestrator.temporal.signal_bridge import send_temporal_signal


app = FastAPI(title="Cory Admissions API")

# Attach middleware first
setup_middleware(app)

# Health check
@app.get("/healthz")
def healthz():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

# Routers
app.include_router(webhook_router, prefix="/webhooks")
app.include_router(sms_router)
app.include_router(email_router)
app.include_router(voice_router)
app.include_router(wa_router)

# ✅ Idempotency cache
idempotency_cache = IdempotencyCache(ttl_seconds=300)
app.state.idempotency = idempotency_cache
app.state.processed_refs = idempotency_cache

# ✅ Real process_event function (Temporal bridge)
async def process_event(channel: str, event):
    """
    Sends the normalized event to the Temporal workflow via signal bridge.
    """
    workflow_id = (
        event.metadata.get("workflow_id")
        or event.payload.get("workflow_id")
        or "default-workflow"
    )

    event_dict = event.model_dump()
    success = await send_temporal_signal(workflow_id, event_dict)
    return success

app.state.process_event_fn = process_event

