import asyncio
from datetime import timedelta
from temporalio.client import Client

async def create_schedule(enrollment_id: str, action: str, payload: dict, policy: dict):
    client = await Client.connect("localhost:7233")
    await client.create_schedule(
        schedule_id=f"enr-{enrollment_id}",
        schedule=dict(
            spec=dict(intervals=[{"every": timedelta(minutes=5)}]),
            action=dict(
                start_workflow=dict(
                    workflow_type="CampaignWorkflow",
                    task_queue="cory-campaigns",
                    args=[enrollment_id, action, payload, policy],
                )
            ),
        ),
    )

if __name__ == "__main__":
    asyncio.run(create_schedule("demo-enr", "send_sms", {"to":"+15551234567","body":"hi"}, {"max_attempts":1}))
