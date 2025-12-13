import asyncio
from temporalio.client import Client
from temporalio.worker import Worker
from uuid import uuid4

# The workflow you are testing
from app.orchestrator.temporal.workflows.campaign import CampaignWorkflow

# Activities (REAL Twilio + REAL Synthflow)
from app.orchestrator.temporal.activities.sms_send import sms_send
from app.orchestrator.temporal.activities.voice_start import voice_start


async def main():

    # 1. Connect to Temporal
    client = await Client.connect("localhost:7233")

    # 2. Start Worker (so the real activities run)
    worker = Worker(
        client,
        task_queue="campaign-queue",
        workflows=[CampaignWorkflow],
        activities=[sms_send, voice_start],
    )

    asyncio.create_task(worker.run())

    # 3. Create a fake campaign with voice + missed-call logic
    workflow_id = f"test-live-call-{uuid4()}"

    steps = [
        {
            "action": "voice_start",
            "payload": {
                "to": "+1YOUR_TEST_NUMBER",
                "lead": {"id": "test-lead"},
                "organization": {"id": "test-org"},
                "campaign_id": "live-test-campaign",
                "campaign_step_id": "step-001",
                "context": {},
                "simulate": False,        # REAL SYNTHFLOW CALL
            },
            "await_timeout_seconds": 25,
        }
    ]

    # 4. Start workflow
    handle = await client.start_workflow(
        CampaignWorkflow.run,
        "live-test-campaign",
        steps,
        id=workflow_id,
        task_queue="campaign-queue"
    )

    print(f"Workflow started: {workflow_id}")

    # 5. Wait for Synthflow call attempt
    print("📞 Waiting 25 seconds for live call attempt...")
    await asyncio.sleep(25)

    # 6. Inject NO-ANSWER signal (you didn't pick up)
    print("❗ Sending provider_event: no_answer")
    await handle.signal(
        "provider_event",
        {"status": "failed", "intent": "voicemail", "data": {"intent": "voicemail"}}
    )

    # First missed-call SMS should go out here (REAL TWILIO)

    print("📱 Waiting 20 seconds for missed-call SMS #1...")
    await asyncio.sleep(20)

    # 7. Workflow will retry call after 15 seconds automatically
    print("📞 Waiting for retry call...")
    await asyncio.sleep(25)

    # 8. Inject second no-answer signal
    print("❗ Sending provider_event: no_answer AGAIN")
    await handle.signal(
        "provider_event",
        {"status": "failed", "intent": "voicemail"}
    )

    # Second missed-call SMS should go out here

    print("📱 Waiting for missed-call SMS #2...")
    await asyncio.sleep(20)

    result = await handle.result()
    print("Workflow finished:")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
