"""
Run a full simulated Admissions Outreach Workflow
using mock (dev) activities step-by-step.

Usage:
    python scripts/test_outreach_mock.py
"""

import asyncio
import logging
from temporalio.client import Client
from temporalio.worker import Worker
from datetime import datetime

# Import the workflow and mock activities
from app.orchestrator.temporal.workflows.admissions_outreach import AdmissionsOutreachWorkflow
from app.orchestrator.temporal.activities.sms_send_dev import sms_send
from app.orchestrator.temporal.activities.email_send_dev import email_send
from app.orchestrator.temporal.activities.voice_start_dev import voice_start
from app.orchestrator.temporal.activities.escalate_to_human import escalate_to_human

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------
TEMPORAL_TARGET = "127.0.0.1:7233"
TEMPORAL_NAMESPACE = "default"
TASK_QUEUE = "rag-q"  # keep your existing queue name

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("outreach-test")


# ---------------------------------------------------------------------
# Test Workflow Runner
# ---------------------------------------------------------------------
async def run_workflow():
    """Run the AdmissionsOutreachWorkflow using mock activities."""
    log.info("🚀 Connecting to Temporal at %s...", TEMPORAL_TARGET)
    client = await Client.connect(TEMPORAL_TARGET, namespace=TEMPORAL_NAMESPACE)

    # Start a lightweight worker (for local run)
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[AdmissionsOutreachWorkflow],
        activities=[sms_send, email_send, voice_start, escalate_to_human],
    )

    lead = {
        "id": "lead-001",
        "name": "Test Student",
        "phone": "+15555550123",
        "email": "test.student@example.com",
    }

    async with worker:
        log.info("🧠 Worker started — launching workflow sequence.")
        handle = await client.start_workflow(
            AdmissionsOutreachWorkflow.run,
            lead,
            id=f"test-outreach-{datetime.utcnow().timestamp()}",
            task_queue=TASK_QUEUE,
        )

        # Stream progress
        log.info("⏳ Waiting for workflow completion...")
        result = await handle.result()
        log.info(f"✅ Workflow finished with result: {result}")


# ---------------------------------------------------------------------
if __name__ == "__main__":
    try:
        asyncio.run(run_workflow())
    except KeyboardInterrupt:
        log.info("KeyboardInterrupt — exiting.")
