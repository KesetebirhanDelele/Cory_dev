# app/web/server.py
# ---------------------------------------------------------------------------
# 🚀 Cory Admissions Web Server Entrypoint (Stable + Safe)
# ---------------------------------------------------------------------------

import os
from datetime import datetime, timezone

from dotenv import load_dotenv, find_dotenv

# --------------------------------------------------------------
# 1) Load .env before anything else
# --------------------------------------------------------------
dotenv_path = find_dotenv(usecwd=True)
if dotenv_path:
    load_dotenv(dotenv_path, override=True)
    print(f"[BOOTSTRAP] Loaded environment from {dotenv_path}")
else:
    print("[BOOTSTRAP] ⚠️ No .env file found — using system environment")

# --------------------------------------------------------------
# After env vars → import everything else
# --------------------------------------------------------------
import uvicorn
from fastapi import FastAPI, Request  # noqa: F401  (Request is used in routers)

from app.web.middleware import setup_middleware
from app.web.idempotency_cache import IdempotencyCache
from app.web.webhook import router as webhook_router
from app.web.sms_webhook import router as sms_router
from app.web.email_webhook import router as email_router
from app.web.voice_webhook import router as voice_router
from app.web.wa_webhook import router as wa_router
from app.web.voice_rag_answer import router as voice_rag_router
from app.web.routes_handoffs import router as handoffs_router
from app.web.routes_kpi import router as kpi_router
from app.web import metrics

# Temporal bridge
from app.orchestrator.temporal.signal_bridge import send_temporal_signal
from app.orchestrator.temporal import signal_bridge


# ---------------------------------------------------------------------------
# 2) APPLICATION FACTORY
# ---------------------------------------------------------------------------
def create_app() -> FastAPI:
    app = FastAPI(title="Cory Admissions Web API")

    # ----------------------------------------------------------
    # 🌐 Temporal Client Initialization
    # ----------------------------------------------------------
    from temporalio.client import Client

    @app.on_event("startup")
    async def startup_temporal():
        try:
            temporal_host = os.getenv("TEMPORAL_HOST_URL", "localhost:7233")
            print(f"[SERVER] Connecting to Temporal at {temporal_host} ...")

            app.state.temporal_client = await Client.connect(temporal_host)

            print("[SERVER] ✅ Temporal client connected")

        except Exception as e:
            print("🚨 TEMPORAL STARTUP FAILED:", e)
            raise  # do NOT swallow errors silently

    # ----------------------------------------------------------
    # ROUTES & MIDDLEWARE
    # ----------------------------------------------------------
    app.mount("/bridge", signal_bridge.app)
    setup_middleware(app)

    app.include_router(webhook_router)
    app.include_router(sms_router)
    app.include_router(email_router)
    app.include_router(voice_router)
    app.include_router(voice_rag_router)
    app.include_router(wa_router)
    app.include_router(handoffs_router)
    app.include_router(kpi_router)
    app.include_router(metrics.router)

    # ----------------------------------------------------------
    # HEALTH CHECK
    # ----------------------------------------------------------
    @app.get("/healthz")
    def healthz():
        return {
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ----------------------------------------------------------
    # Idempotency cache shared by all webhook handlers
    # ----------------------------------------------------------
    idempotency_cache = IdempotencyCache(ttl_seconds=300)
    app.state.idempotency = idempotency_cache
    app.state.processed_refs = idempotency_cache

    # ----------------------------------------------------------
    # 🌉 Event → Temporal Signal Bridge
    # ----------------------------------------------------------
    async def process_event(channel: str, event):
        """
        Called by SMS, email, WhatsApp, etc. to push inbound
        events into running Temporal workflows.
        """
        try:
            workflow_id = (
                event.metadata.get("workflow_id")
                or event.payload.get("workflow_id")
                or "default-workflow"
            )

            event_dict = event.model_dump()
            success = await send_temporal_signal(workflow_id, event_dict)

            return success

        except Exception as e:
            print("🚨 FAILED SENDING TEMPORAL SIGNAL:", e)
            return False

    app.state.process_event_fn = process_event

    return app


# ---------------------------------------------------------------------------
# 3) EXPORT APP
# ---------------------------------------------------------------------------
app = create_app()


# ---------------------------------------------------------------------------
# 4) DEVELOPMENT ENTRYPOINT
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    print(f"🚀 Starting Cory Web API on http://localhost:{port}")
    uvicorn.run(
        "app.web.server:app",
        host="0.0.0.0",
        port=port,
        reload=True,
    )
