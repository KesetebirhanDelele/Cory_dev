# app/web/server.py
from fastapi import FastAPI
from app.web.middleware import RequestIDMiddleware, LoggingMiddleware
from app.web.webhook import router as webhook_router
from app.web.routes_handoffs import router as handoffs_router
from app.web.routes_kpi import router as kpi_router
from app.orchestrator.temporal.signal_bridge import app as signal_app  # ASGI sub-app

def create_app() -> FastAPI:
    app = FastAPI(title="Cory Web API")

    # Middleware order: RequestID first so Logging can include it
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(LoggingMiddleware)

    # Routers (HTTP)
    app.include_router(webhook_router)
    app.include_router(handoffs_router)
    app.include_router(kpi_router)          # <-- ensures /api/v1/kpi exists

    # Mount Temporal signal bridge under a prefix to avoid clobbering root
    # Exposes: POST /temporal/signal
    app.mount("/temporal", signal_app)

    return app

# single app instance exported for uvicorn/tests
app = create_app()
