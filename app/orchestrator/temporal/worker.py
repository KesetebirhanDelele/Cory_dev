import asyncio
from temporalio.client import Client
from temporalio import worker
from app.orchestrator.temporal.workflows.campaign import CampaignWorkflow
from app.orchestrator.temporal.activities.sms_send import run as sms_send
from app.orchestrator.temporal.activities.email_send import run as email_send
from app.orchestrator.temporal.activities.voice_start import run as voice_start
from app.orchestrator.temporal.activities.interactions_log import log as interactions_log
from app.orchestrator.temporal.activities.handoff_create import run as handoff_create

TASK_QUEUE = "cory-campaigns"

async def main():
    client = await Client.connect("localhost:7233")  # or Temporal Cloud endpoint
    async with worker.Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[CampaignWorkflow],
        activities=[sms_send, email_send, voice_start, interactions_log, handoff_create],
    ):
        print(f"Temporal worker started on task queue: {TASK_QUEUE}")
        await asyncio.Event().wait()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
