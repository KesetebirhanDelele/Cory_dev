# app/orchestrator/temporal/signal_bridge.py
import logging
import asyncio

logger = logging.getLogger("cory.signal_bridge")


async def send_temporal_signal(workflow_id: str, event_dict: dict) -> bool:
    """
    Mock Temporal signal bridge.
    In real system: send provider_event(event_dict) signal to Temporal workflow.
    """
    await asyncio.sleep(0)  # Simulate async I/O
    logger.info("Signal sent to workflow", extra={"workflow_id": workflow_id})
    return True

from __future__ import annotations

import os
import logging
from typing import Any, Dict

from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field
from temporalio.client import Client

from app.orchestrator.temporal.workflows.handoff import HandoffWorkflow  # for typed signal

log = logging.getLogger(__name__)

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

class ResolveBody(BaseModel):
    resolution_payload: Dict[str, Any] = Field(default_factory=dict)

# ---- Temporal client dependency (patch in tests as needed) ----
async def get_temporal_client() -> Client:
    target = os.getenv("TEMPORAL_TARGET", "localhost:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    return await Client.connect(target, namespace=namespace)

# ---- Helpers ----
async def _signal_by_name(client: Client, workflow_id: str, signal_name: str, payload: Dict[str, Any]):
    handle = client.get_workflow_handle(workflow_id)
    # Use by-name to support arbitrary signals (keeps generic endpoint flexible)
    await handle.signal_by_name(signal_name, payload)

async def send_handoff_resolve_signal(
    workflow_id: str,
    resolution_payload: Dict[str, Any],
    client: Client | None = None,
):
    """Programmatic helper (used by web layer or tests)."""
    owned_client = False
    if client is None:
        client = await get_temporal_client()
        owned_client = True
    try:
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal(HandoffWorkflow.resolve, resolution_payload or {})
    finally:
        # The Temporal Client doesn't need explicit close currently, but keep hook if that changes.
        if owned_client:
            pass

# ---- Endpoints ----

@app.post("/temporal/signal")
async def signal_temporal(
    payload: SignalPayload,
    client: Client = Depends(get_temporal_client),
):
    """
    Generic signal bridge:
    - payload.signal: signal name on the target workflow
    - payload.event: arbitrary provider event payload
    """
    try:
        await _signal_by_name(
            client=client,
            workflow_id=payload.workflow_id,
            signal_name=payload.signal,
            payload=payload.event.model_dump(),
        )
        return {"ok": True}
    except Exception as e:
        log.exception("Signal failure for %s:%s", payload.workflow_id, payload.signal)
        # Surface a clean 500 to the client
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/handoffs/{workflow_id}/resolve")
async def resolve_handoff(
    workflow_id: str,
    body: ResolveBody,
    client: Client = Depends(get_temporal_client),
):
    """
    Convenience endpoint for the C3.2 flow to resolve a handoff workflow.
    """
    try:
        await send_handoff_resolve_signal(
            workflow_id=workflow_id,
            resolution_payload=body.resolution_payload,
            client=client,
        )
        return {"ok": True}
    except Exception as e:
        log.exception("Resolve signal failed for %s", workflow_id)
        raise HTTPException(status_code=400, detail=str(e))
