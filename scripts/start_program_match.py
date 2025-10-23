import asyncio
import os
import sys
from temporalio.client import Client

async def main(lead_id: str):
    target = os.getenv("TEMPORAL_TARGET", "localhost:7233")
    queue = os.getenv("AI_MATCH_QUEUE", "ai-match-q")
    client = await Client.connect(target)
    handle = await client.start_workflow(
        "ProgramMatchWf",
        lead_id,
        id=f"match-{lead_id}",
        task_queue=queue,
    )
    print(await handle.result())

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
