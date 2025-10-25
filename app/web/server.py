# app/web/server.py
from fastapi import FastAPI
from datetime import datetime, timezone
from app.web import metrics

from app.web.middleware import setup_middleware
from app.web.webhook import router as webhook_router
from app.web.idempotency_cache import IdempotencyCache
from app.web.sms_webhook import router as sms_router
from app.web.email_webhook import router as email_router
from app.web.voice_webhook import router as voice_router
from app.web.wa_webhook import router as wa_router

# ✅ Temporal bridge
from app.orchestrator.temporal.signal_bridge import send_temporal_signal
from app.web.routes_handoffs import router as handoffs_router
from app.web.routes_kpi import router as kpi_router
from app.orchestrator.temporal import signal_bridge  # sub-app

def create_app() -> FastAPI:
    app = FastAPI(title="Cory Web API")

    # ✅ Mount Temporal bridge
    app.mount("/bridge", signal_bridge.app)

    # ✅ Middleware
    setup_middleware(app)

    # ✅ Routers
    app.include_router(webhook_router)
    app.include_router(sms_router)
    app.include_router(email_router)
    app.include_router(voice_router)
    app.include_router(wa_router)
    app.include_router(handoffs_router)
    app.include_router(kpi_router)
    app.include_router(metrics.router)

    # ✅ Health check
    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

    @app.get("/readyz")
    async def readyz():
     """
     Readiness probe for orchestrator and DB.
     For now, returns simple 200 with status 'ready'.
     """
     return {"status": "ready"}

    # ✅ Idempotency cache
    idempotency_cache = IdempotencyCache(ttl_seconds=300)
    app.state.idempotency = idempotency_cache
    app.state.processed_refs = idempotency_cache

    # ✅ Temporal process_event
    async def process_event(channel: str, event):
        workflow_id = (
            event.metadata.get("workflow_id")
            or event.payload.get("workflow_id")
            or "default-workflow"
        )
        event_dict = event.model_dump()
        success = await send_temporal_signal(workflow_id, event_dict)
        return success

    app.state.process_event_fn = process_event

    return app

# Export for uvicorn/pytest
app = create_app()
