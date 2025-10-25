# app/web/middleware.py
import uuid
import time
from fastapi import Request
from typing import Callable
from app.web import metrics as metrics_mod
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        start = time.time()

        # Count every request
        metrics_mod.WEBHOOK_TOTAL.labels(method=request.method, path=request.url.path).inc()

        response = await call_next(request)

        # Measure latency
        latency = time.time() - start
        metrics_mod.WEBHOOK_LATENCY.observe(latency)

        # Status counters
        status = response.status_code
        if 200 <= status < 300:
            metrics_mod.WEBHOOK_2XX.inc()
        elif 400 <= status < 500:
            metrics_mod.WEBHOOK_4XX.inc()

        return response
    
def setup_middleware(app: FastAPI):
    """Attach all middlewares (like Request ID) to FastAPI app."""
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(MetricsMiddleware)

