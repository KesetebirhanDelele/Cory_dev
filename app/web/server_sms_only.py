# app/web/server_sms_only.py

from fastapi import FastAPI
from datetime import datetime, timezone

from app.web.sms_webhook import router as sms_router

app = FastAPI(title="Cory SMS Test API")

app.include_router(sms_router)


@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
