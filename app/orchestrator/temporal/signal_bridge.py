# app/orchestrator/temporal/signal_bridge.py
from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field
from temporalio.client import Client

# FastAPI app exported for tests and mounting
app = FastAPI()

# ---- Models ----
class ProviderEvent(BaseModel):
    status: str = Field(..., examples=["delivered", "failed", "replied"])
    provider_ref: str = Field(..., examples=["abc123"])
    data: Dict[str, Any] = Field(default_factory=dict)

class SignalPayload(BaseModel):
    workflow_id: str
    signal: str = "provider_event"
    event: ProviderEvent

# ---- Dependency to obtain a Temporal client (patched in tests) ----
async def get_temporal_client() -> Client:
    target = os.getenv("TEMPORAL_TARGET", "localhost:7233")
    return await Client.connect(target)

# ---- Endpoint ----
@app.post("/temporal/signal")
async def signal_temporal(
    payload: SignalPayload,
    client: Client = Depends(get_temporal_client),
):
    try:
        await client.signal_workflow(
            workflow_id=payload.workflow_id,
            signal_name=payload.signal,
            arg=payload.event.model_dump(),
        )
        return {"ok": True}
    except Exception as e:
        # Surface a clean 500 to the test client
        raise HTTPException(status_code=500, detail=str(e))
