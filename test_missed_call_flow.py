"""
End-to-end test for:
- voice_start call attempt
- missed-call SMS #1
- 15 sec wait
- retry call
- missed-call SMS #2

This simulates provider events so you can test
WITHOUT Synthflow or Twilio.
"""

import asyncio
from temporalio.client import Client
from temporalio.worker import Worker
from datetime import timedelta

# Your existing campaign workflow + activities
from app.orchestrator.temporal.workflows.campaign import CampaignWorkflow
from app.orchestrator.temporal.activities.voice_start import voice_start
from app.orchestrator.temporal.activities.sms_send import sms_send
from app.orchestrator.temporal.activities.email_send import email_send


# ------------------------------
# Test Configuration
# ------------------------------

TEST_WORKFLOW_ID = "test-missed-call-flow"
TEST_TASK_QUEUE = "cory-test-queue"

TEST_CAMPAIGN_ID = "TEST-CAMPAIGN"
PHONE = "+15550001"


# ------------------------------
# Build a fake campaign sequence
# ------------------------------
STEPS = [
    {
        "action": "voice_start",
        "payload": {
            "to": PHONE,
            "lead": {"id": "test-lead"},
            "organization": {"id": "test-org"},
            "campaign_id": TEST_CAMPAIGN_ID,
            "campaign_step_id": "step-call-1",
            "simulate": True,
        },
        "await_timeout_seconds": 5,    # simulate short timeout for testing
        "context": {
            "enrollment_id": "enroll-123",
            "registration_id": "reg-123",
            "campaign_step_id": "step-call-1",
            "org_id": "test-org",
            "project_id": "proj-123",
            "phone": PHONE,
        },
    }
]


# ------------------------------
# Test Execution
# ------------------------------
async def run_test():
    client = await Client.connect("localhost:7233")

    # Create a worker so activities resolve
    worker = Worker(
        client,
        task_queue=TEST_TASK_QUEUE,
        workflows=[CampaignWorkflow],
        activities=[voice_start, sms_send, email_send],
    )

    async with worker:
        # 1️⃣ Start workflow execution
        print("🚀 Starting workflow…")
        handle = await client.start_workflow(
            CampaignWorkflow.run,
            TEST_CAMPAIGN_ID,
            STEPS,
            id=TEST_WORKFLOW_ID,
            task_queue=TEST_TASK_QUEUE,
        )

        # 2️⃣ Simulate no-answer for the first call
        print("📡 Sending provider_event: no_answer")
        await handle.signal(
            "provider_event",
            {"status": "no_answer", "data": {"intent": "no_answer"}}
        )

        # 3️⃣ Wait for 5 seconds + 15-second internal sleep + retry call
        print("⏳ Waiting for retry call to trigger…")
        await asyncio.sleep(25)

        # 4️⃣ Simulate no-answer AGAIN on retry
        print("📡 Sending provider_event: no_answer (retry)")
        await handle.signal(
            "provider_event",
            {"status": "no_answer", "data": {"intent": "no_answer"}}
        )

        print("⏳ Waiting for SMS #2…")
        await asyncio.sleep(5)

        # 5️⃣ Final result
        result = await handle.result()
        print("\n\n==================== FINAL WORKFLOW RESULT ====================")
        print(result)
        print("===============================================================\n")

        print("🎉 Test completed successfully!")


if __name__ == "__main__":
    asyncio.run(run_test())
