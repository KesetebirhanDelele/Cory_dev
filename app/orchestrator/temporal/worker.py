import asyncio
import os
import logging

from temporalio.client import Client
from temporalio.worker import Worker

# Workflows & Activities
from app.orchestrator.temporal.workflows.campaign import CampaignWorkflow
from app.orchestrator.temporal.activities.sms_send import sms_send
from app.orchestrator.temporal.activities.email_send import email_send
from app.orchestrator.temporal.activities.voice_start import voice_start

TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "cory-campaigns")
TEMPORAL_TARGET = os.getenv("TEMPORAL_TARGET", "localhost:7233")  # cloud: "<ns>.<region>.tmprl.cloud:7233"

logger = logging.getLogger(__name__)

async def run():
    client = await Client.connect(TEMPORAL_TARGET)
    logger.info("Connected to Temporal: %s", TEMPORAL_TARGET)

    # Register workflow(s) and activity(ies)
    async with Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[CampaignWorkflow],
        activities=[sms_send, email_send, voice_start],
    ):
        logger.info("Worker started on task queue: %s", TASK_QUEUE)
        await asyncio.Event().wait()  # idle forever

def main():
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())

if __name__ == "__main__":
    main()
