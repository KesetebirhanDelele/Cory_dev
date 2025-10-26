# app/orchestrator/temporal/worker_rag.py
import asyncio
import os
import logging
from temporalio.client import Client
from temporalio.worker import Worker
from dotenv import load_dotenv, find_dotenv

# Load environment variables
load_dotenv(find_dotenv(usecwd=True), override=False)

# ---------------- Workflows ----------------
from app.orchestrator.temporal.workflows.rag_answer import AnswerBuilderWf
from app.orchestrator.temporal.workflows.answer_builder import AnswerWorkflow

# ---------------- Activities ----------------
from app.orchestrator.temporal.activities.rag_retrieve import retrieve_chunks
from app.orchestrator.temporal.activities.rag_compose import compose_answer
from app.orchestrator.temporal.activities.rag_redact import redact_enforce
from app.orchestrator.temporal.activities.rag_route import route

# ---------------- Logging ----------------
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s - %(message)s")


async def main():
    """Start the Temporal RAG worker process."""
    temporal_target = os.getenv("TEMPORAL_TARGET", "127.0.0.1:7233")
    temporal_namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    task_queue = os.getenv("TEMPORAL_TASK_QUEUE", "rag-q")

    log.info("Connecting to Temporal | target=%s | namespace=%s", temporal_target, temporal_namespace)
    client = await Client.connect(temporal_target, namespace=temporal_namespace)

    log.info("Starting RAG worker on queue: %s", task_queue)
    log.info("Registered workflows: AnswerBuilderWf, AnswerWorkflow")
    log.info("Registered activities: retrieve_chunks, redact_enforce, compose_answer, route")

    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[AnswerBuilderWf, AnswerWorkflow],
        activities=[retrieve_chunks, redact_enforce, compose_answer, route],
    )

    try:
        await worker.run()
    except KeyboardInterrupt:
        log.info("RAG worker stopped manually.")


if __name__ == "__main__":
    asyncio.run(main())
