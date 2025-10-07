# app/web/middleware.py
import uuid
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("cory.web")

class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Ensures every incoming request has a unique X-Request-Id header.
    Adds it to request.state and response headers.
    """

    async def dispatch(self, request: Request, call_next):
        # Try to reuse an incoming header, else create a new UUID4
        req_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())

        # Store in request context
        request.state.request_id = req_id

        # Continue processing
        response = await call_next(request)

        # Add to response header
        response.headers["X-Request-Id"] = req_id
        return response


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Adds simple request start/end logs, with the request_id for traceability.
    """

    async def dispatch(self, request: Request, call_next):
        req_id = getattr(request.state, "request_id", None)
        logger.info(
            "request.start",
            extra={
                "request_id": req_id,
                "method": request.method,
                "path": str(request.url.path),
            },
        )
        response = await call_next(request)
        logger.info(
            "request.end",
            extra={"request_id": req_id, "status_code": response.status_code},
        )
        return response

