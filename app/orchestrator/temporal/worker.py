# app/orchestrator/temporal/worker.py
import asyncio
import logging
import os
import signal
import sys

from temporalio.client import Client
from temporalio.worker import Worker

from app.orchestrator.temporal.workflows.campaign import CampaignWorkflow
from app.orchestrator.temporal.workflows.handoff import HandoffWorkflow

from app.orchestrator.temporal.activities.sms_send import sms_send
from app.orchestrator.temporal.activities.email_send import email_send
from app.orchestrator.temporal.activities.voice_start import voice_start
from app.orchestrator.temporal.activities.handoff_create import (
    create_handoff,
    resolve_handoff_rpc,
    mark_timed_out,
)

from app.common.tracing import setup_logging, set_trace_id  # NEW
from temporalio import activity  # ensure this import exists
from app.common.tracing import set_trace_id

# ------------------------------------------------------------------------------
# Config: prefer central module if available; fall back to environment defaults.
# ------------------------------------------------------------------------------
try:
    from app.orchestrator.temporal.config import (  # type: ignore
        TEMPORAL_TARGET as _CFG_TARGET,
        TEMPORAL_NAMESPACE as _CFG_NAMESPACE,
        TASK_QUEUE as _CFG_TASK_QUEUE,
    )
    TEMPORAL_TARGET = _CFG_TARGET
    TEMPORAL_NAMESPACE = _CFG_NAMESPACE
    TASK_QUEUE = _CFG_TASK_QUEUE
except Exception:
    TEMPORAL_TARGET = os.getenv("TEMPORAL_TARGET", "127.0.0.1:7233")
    TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
    TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "cory-campaigns")

log = logging.getLogger(__name__)


async def _preflight(client: Client) -> None:
    """
    Try a lightweight info call if supported; otherwise skip without failing.
    Compatible with older Temporal Python SDKs that lack get_system_info().
    """
    try:
        # Newer SDKs expose client.workflow_service.get_system_info()
        svc = getattr(client, "workflow_service", None)
        if svc and hasattr(svc, "get_system_info"):
            info = await svc.get_system_info()           # ok on newer SDKs
            server_version = getattr(info, "server_version", "unknown")
            log.info("Temporal server version: %s", server_version)
        else:
            log.info("Preflight: skipping system info (SDK lacks get_system_info).")
    except Exception as e:
        # Don't block startup on optional preflight
        log.warning("Preflight info check failed (non-fatal): %s", e)

async def run() -> None:
    # On Windows, Proactor policy is default; Temporal works fine there,
    # but some environments prefer Selector. Toggle via env if needed.
    if sys.platform == "win32" and os.getenv("USE_SELECTOR_LOOP", "0") == "1":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    log.info(
        "Starting worker | target=%s namespace=%s queue=%s",
        TEMPORAL_TARGET, TEMPORAL_NAMESPACE, TASK_QUEUE
    )

    client = await Client.connect(TEMPORAL_TARGET, namespace=TEMPORAL_NAMESPACE)
    await _preflight(client)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    # Register signal handlers only where supported (POSIX).
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                pass

    activities = [
        sms_send,
        email_send,
        voice_start,
        create_handoff,
        resolve_handoff_rpc,
        mark_timed_out,
    ]
    workflows = [CampaignWorkflow, HandoffWorkflow]

    try:
        async with Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=workflows,
            activities=activities,
        ):
            log.info("Worker started on task queue: %s", TASK_QUEUE)
            if sys.platform == "win32":
                # On Windows, just wait forever; Ctrl+C raises KeyboardInterrupt.
                await asyncio.Future()
            else:
                await stop_event.wait()
    except KeyboardInterrupt:
        log.info("KeyboardInterrupt — shutting down worker")
    except asyncio.CancelledError:
        log.info("Worker cancelled — shutting down")
    finally:
        # Client is closed by the context manager on exit; nothing special needed here.
        log.info("Worker stopped")

def with_trace_id(fn):
    async def wrapper(*args, **kwargs):
        info = activity.info()
        headers = getattr(info, "headers", {}) or {}
        tid = headers.get(b"trace_id")
        set_trace_id(tid.decode("utf-8", "ignore") if isinstance(tid, (bytes, bytearray)) else None)
        try:
            return await fn(*args, **kwargs)
        finally:
            set_trace_id(None)
    return wrapper

activities = [
    with_trace_id(sms_send),
    with_trace_id(email_send),
    with_trace_id(voice_start),
    with_trace_id(create_handoff),
    with_trace_id(resolve_handoff_rpc),
    with_trace_id(mark_timed_out),
]
# then pass activities=activities to Worker(...)

def main() -> None:
    from app.common.tracing import setup_logging
    setup_logging()  # must be first to install the record factory
    asyncio.run(run())

if __name__ == "__main__":
    main()
