# app/orchestrator/temporal/workflows/answer_builder.py
from __future__ import annotations
from datetime import timedelta
from typing import Any, Dict, List
from temporalio import workflow

# ✅ Important: mark heavy imports as “passed through” to bypass sandbox restrictions
with workflow.unsafe.imports_passed_through():
    from app.orchestrator.temporal.activities.rag_retrieve import retrieve_chunks
    from app.orchestrator.temporal.activities.rag_redact import redact_enforce
    from app.orchestrator.temporal.activities.rag_compose import compose_answer


@workflow.defn(name="AnswerWorkflow")
class AnswerWorkflow:
    """
    Temporal workflow for building AI answers from retrieved and redacted content.

    Steps:
      1. Retrieve chunks from Supabase (RAG)
      2. Apply redaction rules
      3. Compose the final contextual answer
    """

    @workflow.run
    async def run(self, query: str, inbound_id: str, threshold: float) -> Dict[str, Any]:
        workflow.logger.info(
            "AnswerWorkflow started | query=%s inbound_id=%s threshold=%.2f",
            query, inbound_id, threshold,
        )

        # 1️⃣ Retrieve candidate chunks
        workflow.logger.info("Step 1: Retrieving chunks…")
        chunks: List[Dict[str, Any]] = await workflow.execute_activity(
            retrieve_chunks,
            args=[query, inbound_id, threshold],
            start_to_close_timeout=timedelta(seconds=60),
        )
        workflow.logger.info("Retrieved %d chunks", len(chunks))

        # 2️⃣ Apply redaction policy
        workflow.logger.info("Step 2: Redacting sensitive info…")
        redacted_chunks: List[Dict[str, Any]] = await workflow.execute_activity(
            redact_enforce,
            args=[chunks],
            start_to_close_timeout=timedelta(seconds=30),
        )
        workflow.logger.info(
            "Redaction complete | before=%d after=%d",
            len(chunks), len(redacted_chunks)
        )

        # 3️⃣ Compose final answer
        workflow.logger.info("Step 3: Composing final answer…")
        result: Dict[str, Any] = await workflow.execute_activity(
            compose_answer,
            args=[{"question": query, "chunks": redacted_chunks}],
            start_to_close_timeout=timedelta(seconds=60),
        )

        workflow.logger.info("✅ Answer composition done | returning final result.")
        return result
