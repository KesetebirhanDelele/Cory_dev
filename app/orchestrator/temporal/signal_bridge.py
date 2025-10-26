# app/orchestrator/temporal/signal_bridge.py
from __future__ import annotations

import os
import asyncio
import logging
from datetime import timedelta
from typing import Any, Dict, Optional

from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field
from temporalio.client import Client

from app.orchestrator.temporal.workflows.handoff import HandoffWorkflow
from app.orchestrator.temporal.workflows.answer_builder import AnswerWorkflow
from temporalio.common import WorkflowIDReusePolicy

logger = logging.getLogger("cory.signal_bridge")

# Optional: exported FastAPI app for local testing
app = FastAPI(title="Temporal Signal Bridge", version="1.0")

# --------------------------------------------------------------------------
# ⚙️ Temporal Client Helpers
# --------------------------------------------------------------------------

async def get_temporal_client() -> Client:
    """Establish a connection to the Temporal server."""
    target = os.getenv("TEMPORAL_TARGET", "localhost:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    try:
        client = await Client.connect(target, namespace=namespace)
        return client
    except Exception as e:
        logger.exception("❌ Failed to connect to Temporal at %s: %s", target, e)
        raise HTTPException(status_code=503, detail=f"Temporal unavailable: {e}")


# --------------------------------------------------------------------------
# 🔹 Universal Workflow Signal Bridge (with auto-start)
# --------------------------------------------------------------------------

async def signal_workflow(
    signal_name: str,
    payload: Dict[str, Any],
    workflow_id: Optional[str] = None,
    task_queue: str = "rag-q",
) -> bool:
    """
    Sends a signal to an existing workflow or auto-starts one if not found.
    Compatible with Temporal 1.18+ SDK.
    """
    workflow_id = workflow_id or "answer-builder-00000000-0000-0000-0000-000000000042"
    target = os.getenv("TEMPORAL_TARGET", "localhost:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")

    try:
        client = await Client.connect(target, namespace=namespace)

        # ✅ Handle both Twilio and lowercase field styles
        body_text = payload.get("Body") or payload.get("body") or ""
        if not body_text:
            logger.warning("Signal payload missing 'Body' or 'body' field")

        await client.start_workflow(
            AnswerWorkflow.run,
            args=[body_text, "inbound-signal", 0.5],
            id=workflow_id,
            task_queue=task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            start_signal=signal_name,
            start_signal_args=[payload],
        )

        logger.info(
            "✅ Signal dispatched | workflow=%s | signal=%s | payload=%s",
            workflow_id, signal_name, payload,
        )
        return True

    except Exception as e:
        logger.exception("❌ Failed to send signal '%s' to %s: %s", signal_name, workflow_id, e)
        return False

# --------------------------------------------------------------------------
# 🧪 Mock Function for Unit Tests
# --------------------------------------------------------------------------

async def send_temporal_signal(workflow_id: str, event_dict: dict) -> bool:
    """Simulated Temporal signal bridge for tests."""
    await asyncio.sleep(0)
    logger.info("🧪 Mock signal sent", extra={"workflow_id": workflow_id})
    return True


# --------------------------------------------------------------------------
# 📦 Pydantic Models for Request Schema
# --------------------------------------------------------------------------

class ProviderEvent(BaseModel):
    status: str = Field(..., examples=["delivered", "failed", "replied"])
    provider_ref: str = Field(..., examples=["abc123"])
    data: Dict[str, Any] = Field(default_factory=dict)


class SignalPayload(BaseModel):
    workflow_id: str
    signal: str = Field("provider_event")
    event: ProviderEvent


class ResolveBody(BaseModel):
    resolution_payload: Dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# 🧩 Handoff Helper Signals
# --------------------------------------------------------------------------

async def send_handoff_resolve_signal(
    workflow_id: str,
    resolution_payload: Dict[str, Any],
    client: Optional[Client] = None,
):
    """Send a resolve signal to HandoffWorkflow."""
    owned_client = False
    if client is None:
        client = await get_temporal_client()
        owned_client = True
    try:
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal(HandoffWorkflow.resolve, resolution_payload or {})
        logger.info("📨 Sent resolve signal to handoff workflow %s", workflow_id)
    finally:
        if owned_client:
            await client.close()


# --------------------------------------------------------------------------
# 🌐 FastAPI Endpoints
# --------------------------------------------------------------------------

@app.post("/temporal/signal")
async def signal_temporal(
    payload: SignalPayload,
    client: Client = Depends(get_temporal_client),
):
    """
    Send a generic signal to any workflow by name.
    """
    try:
        await client.signal_with_start(
            AnswerWorkflow.run,
            args=[payload.event.status, "api-signal", 0.5],
            id=payload.workflow_id,
            signal=payload.signal,
            signal_args=[payload.event.model_dump()],
            task_queue="rag-q",
            execution_timeout=timedelta(hours=1),
            id_reuse_policy="allow_duplicate",
        )
        return {"ok": True}
    except Exception as e:
        logger.exception("Signal failure for %s:%s", payload.workflow_id, payload.signal)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/handoffs/{workflow_id}/resolve")
async def resolve_handoff(
    workflow_id: str,
    body: ResolveBody,
    client: Client = Depends(get_temporal_client),
):
    """Send a resolve signal to an active HandoffWorkflow."""
    try:
        await send_handoff_resolve_signal(
            workflow_id=workflow_id,
            resolution_payload=body.resolution_payload,
            client=client,
        )
        return {"ok": True}
    except Exception as e:
        logger.exception("Resolve signal failed for %s", workflow_id)
        raise HTTPException(status_code=400, detail=str(e))
