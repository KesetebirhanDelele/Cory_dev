# scripts/missed_call_worker_dev.py
from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv
from temporalio.client import Client
from temporalio.worker import Worker

from app.common.tracing import setup_logging
from app.orchestrator.temporal.workflows.missed_call_followup import (
    MissedCallFollowupWorkflow,
)
from app.orchestrator.temporal.activities.sms_send import sms_send
from app.orchestrator.temporal.activities.nurture_enroll import nurture_enroll

log = logging.getLogger("cory.missed_call_worker_dev")

TASK_QUEUE = os.getenv("TEMPORAL_MISSED_CALL_TEST_QUEUE", "missed-call-dev-q")
TEMPORAL_TARGET = os.getenv("TEMPORAL_TARGET", "127.0.0.1:7233")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")


async def main() -> None:
    load_dotenv()
    setup_logging()

    workflows = [MissedCallFollowupWorkflow]
    activities = [sms_send, nurture_enroll]

    log.info(
        "Connecting Temporal worker | target=%s | namespace=%s | queue=%s",
        TEMPORAL_TARGET,
        TEMPORAL_NAMESPACE,
        TASK_QUEUE,
    )

    client = await Client.connect(TEMPORAL_TARGET, namespace=TEMPORAL_NAMESPACE)
    log.info("✅ Connected to Temporal")

    log.info(
        "🚀 Starting MissedCall worker dev | workflows=%s | activities=%s",
        [w.__name__ for w in workflows],
        [a.__name__ for a in activities],
    )

    worker = Worker(
        client=client,
        task_queue=TASK_QUEUE,
        workflows=workflows,
        activities=activities,
    )

    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
