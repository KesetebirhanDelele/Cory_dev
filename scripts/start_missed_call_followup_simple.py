# scripts/start_missed_call_followup_simple.py
from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv
from temporalio.client import Client

from app.orchestrator.temporal.workflows.missed_call_followup import (
    MissedCallFollowupWorkflow,
)

log = logging.getLogger("cory.scripts.start_missed_call_followup_simple")

# Hard-code for your test contact/enrollment
PHONE = "+15714782790"  # your phone in E.164
ENROLLMENT_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1"
CAMPAIGN_ID = "77777777-7777-7777-7777-777777777771"
SMART_NURTURE_ID = "77777777-7777-7777-7777-777777777773"

TEMPORAL_TARGET = os.getenv("TEMPORAL_TARGET", "127.0.0.1:7233")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
TASK_QUEUE = os.getenv("TEMPORAL_MISSED_CALL_TEST_QUEUE", "missed-call-dev-q")


async def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    log.info(
        "Connecting to Temporal at %s (namespace=%s)...",
        TEMPORAL_TARGET,
        TEMPORAL_NAMESPACE,
    )
    client = await Client.connect(TEMPORAL_TARGET, namespace=TEMPORAL_NAMESPACE)
    log.info("✅ Connected to Temporal")

    workflow_id = f"missed-call-manual-{ENROLLMENT_ID}"
    log.info(
        "🚀 Starting MissedCallFollowupWorkflow | phone=%s | enrollment=%s | "
        "campaign=%s | nurture=%s | queue=%s",
        PHONE,
        ENROLLMENT_ID,
        CAMPAIGN_ID,
        SMART_NURTURE_ID,
        TASK_QUEUE,
    )

    handle = await client.start_workflow(
        MissedCallFollowupWorkflow.run,
        id=workflow_id,
        task_queue=TASK_QUEUE,
        args=[PHONE, ENROLLMENT_ID, CAMPAIGN_ID, SMART_NURTURE_ID],
    )

    # For the new SDK this is usually available:
    log.info(
        "🎯 MissedCallFollowupWorkflow started | workflow_id=%s | run_id=%s",
        handle.id,
        getattr(handle, "first_execution_run_id", None),
    )


if __name__ == "__main__":
    asyncio.run(main())
