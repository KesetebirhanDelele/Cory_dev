# app/orchestrator/temporal/worker.py
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from typing import List

from temporalio.client import Client
from temporalio.worker import Worker

from app.common.tracing import setup_logging

# -------- Existing workflows/activities --------
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

# -------- C5.1: Program/Persona Matching --------
from app.orchestrator.temporal.workflows.program_match import ProgramMatchWf
from app.orchestrator.temporal.activities import program_match as match_acts

# -------- Config: prefer central module; else env --------
try:
    from app.orchestrator.temporal.config import (  # type: ignore
        TEMPORAL_TARGET as _CFG_TARGET,
        TEMPORAL_NAMESPACE as _CFG_NAMESPACE,
        TASK_QUEUE as _CFG_TASK_QUEUE,
        AI_MATCH_QUEUE as _CFG_AI_MATCH_QUEUE,
    )
    TEMPORAL_TARGET = _CFG_TARGET
    TEMPORAL_NAMESPACE = _CFG_NAMESPACE
    TASK_QUEUE = _CFG_TASK_QUEUE
    AI_MATCH_QUEUE = _CFG_AI_MATCH_QUEUE
except Exception:
    TEMPORAL_TARGET = os.getenv("TEMPORAL_TARGET", "127.0.0.1:7233")
    TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
    TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "cory-campaigns")
    AI_MATCH_QUEUE = os.getenv("AI_MATCH_QUEUE", "ai-match-q")

log = logging.getLogger(__name__)


# ---------------- Helpers ----------------
async def _preflight(client: Client) -> None:
    """Best-effort server version log; no-ops on SDKs without this RPC."""
    try:
        from temporalio.api.workflowservice.v1 import GetSystemInfoRequest  # type: ignore
        info = await client.workflow_service.get_system_info(GetSystemInfoRequest())  # type: ignore
        log.info("Temporal server version: %s", getattr(info, "server_version", "unknown"))
    except Exception:
        # Quietly skip on any mismatch
        pass


async def _serve_queue(client: Client, task_queue: str, workflows: List, activities: List):
    log.info("Initializing worker for queue: %s", task_queue)
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=workflows,
        activities=activities,  # register callables directly
    )
    try:
        log.info("Worker starting on task queue: %s", task_queue)
        await worker.run()  # blocks until cancelled
    except Exception as e:
        log.exception("Worker crashed on queue %s: %s", task_queue, e)
        raise


# ---------------- Launcher ----------------
async def run() -> None:
    # Optional Windows selector loop for libs that need it
    if sys.platform == "win32" and os.getenv("USE_SELECTOR_LOOP", "0") == "1":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    log.info(
        "Starting workers | target=%s namespace=%s queues=[%s, %s]",
        TEMPORAL_TARGET,
        TEMPORAL_NAMESPACE,
        TASK_QUEUE,
        AI_MATCH_QUEUE,
    )

    client = await Client.connect(TEMPORAL_TARGET, namespace=TEMPORAL_NAMESPACE)
    await _preflight(client)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                pass

    # Campaign/Handoff worker
    campaigns_workflows = [CampaignWorkflow, HandoffWorkflow]
    campaigns_activities = [
        sms_send,
        email_send,
        voice_start,
        create_handoff,
        resolve_handoff_rpc,
        mark_timed_out,
    ]

    # ProgramMatch worker
    match_workflows = [ProgramMatchWf]
    match_activities = [
        match_acts.load_rules,
        match_acts.deterministic_score,
        match_acts.llm_score_fallback,
        match_acts.persist_scores,
    ]

    # Start both queues concurrently and surface failures
    worker_tasks = [
        asyncio.create_task(
            _serve_queue(client, TASK_QUEUE, campaigns_workflows, campaigns_activities), name="campaigns"
        ),
        asyncio.create_task(
            _serve_queue(client, AI_MATCH_QUEUE, match_workflows, match_activities), name="ai-match"
        ),
    ]

    for t in worker_tasks:
        def _cb(task: asyncio.Task):
            exc = task.exception()
            if exc:
                log.exception("Worker task %s exited with exception: %s", task.get_name(), exc)
        t.add_done_callback(_cb)

    try:
        if sys.platform == "win32":
            await asyncio.Future()  # Ctrl+C -> KeyboardInterrupt
        else:
            await stop_event.wait()
    except KeyboardInterrupt:
        log.info("KeyboardInterrupt — shutting down workers")
    finally:
        for t in worker_tasks:
            t.cancel()
        await asyncio.gather(*worker_tasks, return_exceptions=True)
        log.info("Workers stopped")


def main() -> None:
    setup_logging()  # install record factory first
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
