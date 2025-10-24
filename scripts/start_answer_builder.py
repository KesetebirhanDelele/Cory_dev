# scripts/start_answer_builder.py
import asyncio
import sys
from temporalio.client import Client
from app.orchestrator.temporal.workflows.answer_builder import AnswerWorkflow


async def main(query: str, inbound_id: str, threshold: float):
    """CLI entrypoint to trigger the AnswerWorkflow through Temporal."""
    print("🔗 Connecting to Temporal at localhost:7233 ...")
    client = await Client.connect("localhost:7233", namespace="default")

    print(f"🚀 Starting workflow for inbound_id={inbound_id} ...")
    handle = await client.start_workflow(
        AnswerWorkflow,                           # workflow class
        args=[query, inbound_id, threshold],       # workflow parameters
        id=f"answer-builder-{inbound_id}",         # deterministic workflow ID
        task_queue="rag-q",                        # must match worker queue
    )

    print(f"✅ Workflow started: {handle.id}")
    print("⏳ Waiting for result...")

    try:
        result = await handle.result()
        print("\n🎉 Workflow completed successfully!\n")
        print("------ RESULT JSON ------")
        print(result)
        print("-------------------------\n")
    except Exception as e:
        print(f"❌ Workflow failed: {e}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python scripts/start_answer_builder.py <query> <inbound_id> <threshold>")
        sys.exit(1)

    q, inbound, thr = sys.argv[1], sys.argv[2], float(sys.argv[3])
    asyncio.run(main(q, inbound, thr))
