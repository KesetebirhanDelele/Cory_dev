# app/orchestrator/temporal/worker.py
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from typing import List

from dotenv import load_dotenv, find_dotenv

# --------------------------------------------------------------------------
# 0) Load .env as early as possible
# --------------------------------------------------------------------------
dotenv_path = find_dotenv(usecwd=True)
if dotenv_path:
    load_dotenv(dotenv_path, override=True)
    print(f"[BOOTSTRAP] Loaded .env from {dotenv_path}")
else:
    print("[BOOTSTRAP] ⚠️ No .env file found for worker — using system environment")

from temporalio.client import Client
from temporalio.worker import Worker

from app.common.tracing import setup_logging

# Workflow registry
from app.orchestrator.temporal.workflows.workflow_registry import WORKFLOWS

from app.orchestrator.temporal.workflows.missed_call_followup import (
    MissedCallFollowupWorkflow,
)
from app.orchestrator.temporal.activities.nurture_enroll import nurture_enroll

# Activities
from app.orchestrator.temporal.activities.sms_send import sms_send
from app.orchestrator.temporal.activities.email_send import email_send
from app.orchestrator.temporal.activities.voice_start import voice_start
from app.orchestrator.temporal.activities.handoff_create import (
    create_handoff,
    resolve_handoff_rpc,
    mark_timed_out,
)
from app.orchestrator.temporal.activities.appointment_book import (
    book_appointment_activity,
)
from app.orchestrator.temporal.activities import (
    rag,
    rag_redact,
    rag_compose,
    rag_route,
    sms_summarize,
    program_match as match_acts,
)

from app.agents.enroll_agent import generate_followup_message
from app.data.supabase_repo import patch_activity

# --------------------------------------------------------------------------
# Environment / constants
# --------------------------------------------------------------------------
log = logging.getLogger("cory.worker")

CAMPAIGN_QUEUE = "cory-handoff-queue"
AI_MATCH_QUEUE = "ai-match-q"
RAG_QUEUE = "rag-q"
FOLLOWUP_QUEUE = "followup-q"

TEMPORAL_TARGET = os.getenv("TEMPORAL_TARGET", "localhost:7233")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
async def _connect_temporal(target: str, namespace: str) -> Client:
    log.info(f"Connecting to Temporal {namespace}@{target} ...")
    client = await Client.connect(target, namespace=namespace)
    log.info("Connected to Temporal server.")
    return client


async def _preflight(client: Client):
    from temporalio.api.workflowservice.v1 import GetSystemInfoRequest

    info = await client.workflow_service.get_system_info(GetSystemInfoRequest())
    log.info(f"Temporal server version: {info.server_version}")


async def _serve(client: Client, queue: str, workflows: List, activities: List):
    log.info(
        f"🚀 Starting worker | queue={queue} | "
        f"workflows={len(workflows)} | activities={len(activities)}"
    )
    worker = Worker(
        client=client,
        task_queue=queue,
        workflows=workflows,
        activities=activities,
    )
    await worker.run()


# --------------------------------------------------------------------------
# Main Worker Runner
# --------------------------------------------------------------------------
async def run() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    setup_logging()

    client = await _connect_temporal(TEMPORAL_TARGET, TEMPORAL_NAMESPACE)
    await _preflight(client)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # Windows / limited environments
            pass

    # ------------------------
    # Per-queue workflow groups
    # ------------------------
    from app.orchestrator.temporal.workflows.answer_builder import AnswerWorkflow
    from app.orchestrator.temporal.workflows.program_match import ProgramMatchWf
    from app.orchestrator.temporal.workflows.simulated_followup import (
        SimulatedFollowupWorkflow,
    )

    # Determine which workflows belong to each queue
    campaign_wfs = [
        wf
        for wf in WORKFLOWS
        if wf.__name__ not in {
            "AnswerWorkflow",
            "ProgramMatchWf",
            "SimulatedFollowupWorkflow",
        }
    ]
    # Ensure MissedCallFollowupWorkflow is on the campaign queue
    if MissedCallFollowupWorkflow not in campaign_wfs:
        campaign_wfs.append(MissedCallFollowupWorkflow)

    rag_wfs = [AnswerWorkflow]
    match_wfs = [ProgramMatchWf]
    followup_wfs = [SimulatedFollowupWorkflow]

    # ------------------------
    # Activities per queue
    # ------------------------
    campaign_activities = [
        sms_send,
        email_send,
        voice_start,
        create_handoff,
        resolve_handoff_rpc,
        mark_timed_out,
        patch_activity,
        generate_followup_message,
        book_appointment_activity,
        # 🔥 New: nurture enrollment for Smart Nurture after missed calls
        nurture_enroll,
    ]

    rag_activities = [
        rag.retrieve_chunks,
        rag_redact.redact_enforce,
        rag_compose.compose_answer,
        rag_route.route,
        sms_summarize.sms_summarize_answer,
        sms_send,
    ]

    match_activities = [
        match_acts.load_rules,
        match_acts.deterministic_score,
        match_acts.llm_score_fallback,
        match_acts.persist_scores,
    ]

    followup_activities = [
        patch_activity,
        generate_followup_message,
    ]

    # ------------------------
    # Launch workers
    # ------------------------
    tasks = [
        asyncio.create_task(
            _serve(client, CAMPAIGN_QUEUE, campaign_wfs, campaign_activities),
            name="campaign",
        ),
        asyncio.create_task(
            _serve(client, AI_MATCH_QUEUE, match_wfs, match_activities),
            name="ai-match",
        ),
        asyncio.create_task(
            _serve(client, RAG_QUEUE, rag_wfs, rag_activities),
            name="rag",
        ),
        asyncio.create_task(
            _serve(client, FOLLOWUP_QUEUE, followup_wfs, followup_activities),
            name="followup",
        ),
    ]

    log.info("✅ Worker queues initialized")

    await stop_event.wait()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    log.info("🛑 Workers shut down cleanly.")


def main():
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("KeyboardInterrupt — exiting.")


if __name__ == "__main__":
    main()
