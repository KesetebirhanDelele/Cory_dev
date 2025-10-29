# scripts/start_sim_followup.py
from temporalio.client import Client
import asyncio
from datetime import datetime

async def main():
    client = await Client.connect("localhost:7233")

    workflow_id = f"sim-followup-{int(datetime.now().timestamp())}"
    lead = {
        "id": "19087807-33db-474c-a54c-043e8fbf3f5e",
        "name": "Alex Doe",
        "email": "alex@example.com",
        "phone": "+15555550222",
        "next_channel": "sms"
    }

    handle = await client.start_workflow(
        "SimulatedFollowupWorkflow",  # name of your workflow class
        lead,
        id=workflow_id,
        task_queue="followup-q",
    )
    print(f"✅ Started workflow: {workflow_id}")

asyncio.run(main())
