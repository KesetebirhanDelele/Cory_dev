# app/orchestrator/temporal/worker.py
from __future__ import annotations
import asyncio
import logging
import os
import signal
import sys
from typing import List

from dotenv import load_dotenv, find_dotenv
from temporalio.client import Client
from temporalio.worker import Worker
from app.common.tracing import setup_logging

# Workflows
from app.orchestrator.temporal.workflows.answer_builder import AnswerWorkflow
from app.orchestrator.temporal.workflows.campaign import CampaignWorkflow
from app.orchestrator.temporal.workflows.handoff import HandoffWorkflow
from app.orchestrator.temporal.workflows.program_match import ProgramMatchWf
from app.orchestrator.temporal.workflows.simulated_followup import SimulatedFollowupWorkflow

# Activities
from app.orchestrator.temporal.activities.sms_send import sms_send
from app.orchestrator.temporal.activities.email_send import email_send
from app.orchestrator.temporal.activities.voice_start import voice_start
from app.orchestrator.temporal.activities.handoff_create import (
    create_handoff,
    resolve_handoff_rpc,
    mark_timed_out,
)
from app.orchestrator.temporal.activities import (
    rag_retrieve,
    rag_redact,
    rag_compose,
    rag_route,
    program_match as match_acts,
)
from app.data import supabase_repo as repo
from app.agents.enroll_agent import generate_followup_message

# --------------------------------------------------------------------------
# Environment and Logging Setup
# --------------------------------------------------------------------------
load_dotenv(find_dotenv(usecwd=True), override=False)
print(f"[BOOTSTRAP] Loaded .env from {find_dotenv(usecwd=True)}")

log = logging.getLogger("cory.worker")

# --------------------------------------------------------------------------
# Temporal Configuration
# --------------------------------------------------------------------------
try:
    from app.orchestrator.temporal.config import (
        TEMPORAL_TARGET as _CFG_TARGET,
        TEMPORAL_NAMESPACE as _CFG_NAMESPACE,
        TASK_QUEUE as _CFG_TASK_QUEUE,
        AI_MATCH_QUEUE as _CFG_AI_MATCH_QUEUE,
        RAG_QUEUE as _CFG_RAG_QUEUE,
    )

    TEMPORAL_TARGET = _CFG_TARGET
    TEMPORAL_NAMESPACE = _CFG_NAMESPACE
    TASK_QUEUE = _CFG_TASK_QUEUE
    AI_MATCH_QUEUE = _CFG_AI_MATCH_QUEUE
    RAG_QUEUE = _CFG_RAG_QUEUE

except Exception:
    TEMPORAL_TARGET = os.getenv("TEMPORAL_TARGET", "127.0.0.1:7233")
    TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
    TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "cory-campaigns")
    AI_MATCH_QUEUE = os.getenv("AI_MATCH_QUEUE", "ai-match-q")
    RAG_QUEUE = os.getenv("RAG_QUEUE", "rag-q")

# --------------------------------------------------------------------------
# Helper Functions
# --------------------------------------------------------------------------
async def _preflight(client: Client) -> None:
    """Log Temporal server version."""
    try:
        from temporalio.api.workflowservice.v1 import GetSystemInfoRequest
        info = await client.workflow_service.get_system_info(GetSystemInfoRequest())
        log.info("Temporal server version: %s", getattr(info, "server_version", "unknown"))
    except Exception as e:
        log.warning("Preflight check skipped or failed: %s", e)


async def _connect_temporal(
    target: str, namespace: str, retries: int = 3, delay: int = 3
) -> Client:
    """Connect to Temporal with retry logic."""
    for attempt in range(1, retries + 1):
        try:
            log.info(
                "Connecting to Temporal server (%s@%s) — attempt %d/%d",
                namespace, target, attempt, retries,
            )
            client = await Client.connect(target, namespace=namespace)
            log.info("Connected to Temporal server: %s", target)
            return client
        except Exception as e:
            log.warning("Connection attempt %d failed: %s", attempt, e)
            if attempt < retries:
                await asyncio.sleep(delay)
    raise RuntimeError(f"Failed to connect to Temporal server after {retries} attempts")


async def _serve_queue(
    client: Client,
    queue_name: str,
    workflows: List,
    activities: List,
) -> None:
    """Start and run a Temporal worker for a given queue."""
    log.info("🚀 Starting worker | queue=%s | workflows=%d | activities=%d",
             queue_name, len(workflows), len(activities))
    worker = Worker(
        client=client,
        task_queue=queue_name,
        workflows=workflows,
        activities=activities,
    )
    try:
        await worker.run()
    except asyncio.CancelledError:
        log.info("Worker on %s cancelled — shutting down gracefully", queue_name)
    except Exception as e:
        log.exception("Worker crashed on queue %s: %s", queue_name, e)
        raise

# --------------------------------------------------------------------------
# Main Runner
# --------------------------------------------------------------------------
async def run() -> None:
    """Entrypoint for Temporal workers."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    setup_logging()
    log.info(
        "🧠 Cory Temporal Worker starting | target=%s | namespace=%s | queues=%s",
        TEMPORAL_TARGET, TEMPORAL_NAMESPACE, [TASK_QUEUE, AI_MATCH_QUEUE, RAG_QUEUE],
    )

    client = await _connect_temporal(TEMPORAL_TARGET, TEMPORAL_NAMESPACE)
    await _preflight(client)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    # Define workflow groups
    campaigns_workflows = [CampaignWorkflow, HandoffWorkflow, AnswerWorkflow]
    campaigns_activities = [
        sms_send,
        email_send,
        voice_start,
        create_handoff,
        resolve_handoff_rpc,
        mark_timed_out,
        repo.insert_interaction,
        repo.patch_activity,
        generate_followup_message,
    ]

    match_workflows = [ProgramMatchWf]
    match_activities = [
        match_acts.load_rules,
        match_acts.deterministic_score,
        match_acts.llm_score_fallback,
        match_acts.persist_scores,
    ]

    rag_workflows = [AnswerWorkflow]
    rag_activities = [
        rag_retrieve.retrieve_chunks,
        rag_redact.redact_enforce,
        rag_compose.compose_answer,
        rag_route.route,
    ]

    # ✅ Add a dedicated follow-up worker group
    followup_workflows = [SimulatedFollowupWorkflow]
    followup_activities = [
        repo.insert_interaction,
        repo.patch_activity,
        generate_followup_message,
    ]

    # Launch all workers
    # Launch all workers concurrently
    worker_tasks = [
        asyncio.create_task(
            _serve_queue(client, TASK_QUEUE, campaigns_workflows, campaigns_activities),
            name="campaigns",
        ),
        asyncio.create_task(
            _serve_queue(client, AI_MATCH_QUEUE, match_workflows, match_activities),
            name="ai-match",
        ),
        asyncio.create_task(
            _serve_queue(client, RAG_QUEUE, rag_workflows, rag_activities),
            name="rag",
        ),
        # 👇 Add this new worker
        asyncio.create_task(
            _serve_queue(client, "followup-q", followup_workflows, followup_activities),
            name="followup",
        ),
    ]
    
    log.info(
        "✅ Worker queues initialized: campaigns=%s, ai-match=%s, rag=%s",
        TASK_QUEUE, AI_MATCH_QUEUE, RAG_QUEUE,
    )

    for t in worker_tasks:
        t.add_done_callback(lambda task: (
            log.exception("Worker %s exited with: %s", task.get_name(), task.exception())
            if task.exception() else None
        ))

    try:
        await stop_event.wait()
        log.info("🛑 Stop signal received — shutting down workers...")
    finally:
        for t in worker_tasks:
            t.cancel()
        await asyncio.gather(*worker_tasks, return_exceptions=True)
        log.info("✅ All workers stopped cleanly.")

# --------------------------------------------------------------------------
# Development Simulation Mode
# --------------------------------------------------------------------------
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
MOCK_COMMUNICATION = os.getenv("MOCK_COMMUNICATION", "false").lower() == "true"

if ENVIRONMENT in ("local", "development", "test") or MOCK_COMMUNICATION:
    log.warning("🧪 Running in DEV SIMULATION MODE — using mock communication activities")
    try:
        from app.orchestrator.temporal.activities.sms_send_dev import sms_send as sms_send
        from app.orchestrator.temporal.activities.email_send_dev import email_send as email_send
        from app.orchestrator.temporal.activities.voice_start_dev import voice_start as voice_start
    except ImportError as e:
        log.error(f"⚠️ Failed to import mock activities: {e}")
else:
    log.info("📡 Using live communication providers for SMS, Email, and Voice.")

# --------------------------------------------------------------------------
# CLI Entrypoint
# --------------------------------------------------------------------------
def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("KeyboardInterrupt — exiting.")


if __name__ == "__main__":
    main()
