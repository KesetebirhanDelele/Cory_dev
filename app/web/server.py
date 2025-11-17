# app/web/server.py
# ---------------------------------------------------------------------------
# ✅ Cory Admissions Web Server Entrypoint
# ---------------------------------------------------------------------------

# 🔹 1. Load environment early (critical for SUPABASE_URL, Temporal, etc.)
import os
from dotenv import load_dotenv, find_dotenv

dotenv_path = find_dotenv(usecwd=True)
if dotenv_path:
    load_dotenv(dotenv_path, override=True)
    print(f"[BOOTSTRAP] Loaded environment from {dotenv_path}")
else:
    print("[BOOTSTRAP] ⚠️ No .env file found — using system environment")

# 🔹 2. Continue with normal imports AFTER env vars are loaded
import uvicorn
from datetime import datetime, timezone
from fastapi import FastAPI

from app.web.middleware import setup_middleware
from app.web.idempotency_cache import IdempotencyCache
from app.web.webhook import router as webhook_router
from app.web.sms_webhook import router as sms_router
from app.web.email_webhook import router as email_router
from app.web.voice_webhook import router as voice_router
from app.web.wa_webhook import router as wa_router
from app.web.routes_handoffs import router as handoffs_router
from app.web.routes_kpi import router as kpi_router
from app.web import metrics


# ✅ Temporal bridge (must be imported after .env load)
from app.orchestrator.temporal.signal_bridge import send_temporal_signal
from app.orchestrator.temporal import signal_bridge  # sub-app

# ---------------------------------------------------------------------------
# ✅ Application Factory
# ---------------------------------------------------------------------------
def create_app() -> FastAPI:
    """Initialize FastAPI web app with all routers, middleware, and bridge."""
    app = FastAPI(title="Cory Admissions Web API")

    # ✅ Mount Temporal bridge (exposes /bridge endpoints)
    app.mount("/bridge", signal_bridge.app)

    # ✅ Middleware setup
    setup_middleware(app)

    # ✅ Routers (SMS, Email, Voice, WhatsApp, KPI, etc.)
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

    # ✅ Idempotency cache (shared across webhook handlers)
    idempotency_cache = IdempotencyCache(ttl_seconds=300)
    app.state.idempotency = idempotency_cache
    app.state.processed_refs = idempotency_cache

    # ✅ Temporal signal handler bridge
    async def process_event(channel: str, event):
        """
        Send incoming events (SMS/email/etc.) into Temporal workflows.
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

    return app


# ---------------------------------------------------------------------------
# ✅ App Export for Uvicorn and Tests
# ---------------------------------------------------------------------------
app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    print(f"🚀 Starting Cory Web API on http://localhost:{port}")
    uvicorn.run("app.web.server:app", host="0.0.0.0", port=port, reload=True)
