# app/web/server.py
from fastapi import FastAPI
from app.web.middleware import RequestIDMiddleware, LoggingMiddleware
from app.web.webhook import router as webhook_router
from app.web.routes_handoffs import router as handoffs_router
from app.web.routes_kpi import router as kpi_router

# Mount the ASGI sub-app once
from app.orchestrator.temporal import signal_bridge  # sub-app lives at signal_bridge.app

def create_app() -> FastAPI:
    app = FastAPI(title="Cory Web API")

    # Mount Temporal signal bridge under /bridge
    # Exposes:
    #   POST /bridge/temporal/signal
    #   POST /bridge/handoffs/{workflow_id}/resolve
    app.mount("/bridge", signal_bridge.app)

    # Middleware order: RequestID first so Logging includes it
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(LoggingMiddleware)

    # Routers (HTTP)
    app.include_router(webhook_router)
    app.include_router(handoffs_router)
    app.include_router(kpi_router)  # if this router has prefix /api/v1/kpi, the route will be available

    return app

# single app instance exported for uvicorn/tests
app = create_app()
