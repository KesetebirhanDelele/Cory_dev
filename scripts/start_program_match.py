# scripts/start_answer_builder.py
import asyncio
from temporalio.client import Client
from app.orchestrator.temporal.workflows.answer_builder import AnswerWorkflow

async def main(query: str, inbound_id: str, threshold: float):
    client = await Client.connect("localhost:7233")

    # Correct: use AnswerWorkflow (not AnswerWorkflow.run)
    handle = await client.start_workflow(
        AnswerWorkflow,
        args=[query, inbound_id, threshold],
        id=f"answer-builder-{inbound_id}",
        task_queue="rag-q",  # must match your worker queue
    )

    result = await handle.result()
    print(f"Workflow completed successfully: {result}")

if __name__ == "__main__":
    import sys
    q, inbound, thr = sys.argv[1], sys.argv[2], float(sys.argv[3])
    asyncio.run(main(q, inbound, thr))
