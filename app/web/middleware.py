# app/web/middleware.py
import uuid
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

def setup_middleware(app: FastAPI):
    """Attach all middlewares (like Request ID) to FastAPI app."""
    app.add_middleware(RequestIDMiddleware)

