# scripts/run_ingest_once.py
import asyncio, os
from temporalio.client import Client
from app.orchestrator.temporal.workflows.doc_ingest_cron import DocIngestCronWf
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True), override=False)

async def main():
    client = await Client.connect(os.getenv("TEMPORAL_TARGET","127.0.0.1:7233"),
                                  namespace=os.getenv("TEMPORAL_NAMESPACE","default"))
    h = await client.start_workflow(
        DocIngestCronWf.run,
        id="doc-ingest-manual",
        task_queue=os.getenv("INGEST_TASK_QUEUE","ingest-q"),
    )
    print(await h.result())

if __name__ == "__main__":
    asyncio.run(main())
