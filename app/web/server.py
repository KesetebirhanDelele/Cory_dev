# app/web/server.py
from fastapi import FastAPI
from app.web.middleware import RequestIDMiddleware, LoggingMiddleware
from app.web.webhook import router as webhook_router
from app.orchestrator.temporal.signal_bridge import app as signal_app  # <— add

app = FastAPI(title="Cory API")
app.include_router(webhook_router)
app.mount("", signal_app)  # exposes POST /temporal/signal

def create_app() -> FastAPI:
    app = FastAPI(title="Cory Web API")
    # RequestID should be added before Logging so request_id exists when Logging runs
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(LoggingMiddleware)
    app.include_router(webhook_router)
    return app


# variable uvicorn / test clients will import
app = create_app()
 