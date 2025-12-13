# app/orchestrator/temporal/workflows/rag_answer.py

from temporalio import workflow
from datetime import timedelta


@workflow.defn(name="AnswerWorkflow")
class AnswerBuilderWf:
    """
    End-to-end RAG Workflow:
      1) retrieve_chunks  → returns {"chunks": [...]}
      2) compose_answer   → returns {"answer": str, "citations": [...]}
      3) redact_enforce   → returns {"answer": str, "confidence": float}
      4) route            → writes outbound msg or handoff
    """

    @workflow.run
    async def run(self, question: str, inbound_msg_id: str, threshold: float):
        workflow.logger.info(
            f"[AnswerWorkflow] Starting workflow | question='{question}' | "
            f"inbound_msg_id={inbound_msg_id} | threshold={threshold}"
        )

        # ----------------------------------------------------------------------
        # 1) RETRIEVE
        # ----------------------------------------------------------------------
        retrieve_args = {
            "query": question,
            "threshold": threshold,
        }

        chunks_result = await workflow.execute_activity(
            "retrieve_chunks",
            retrieve_args,                         # MUST be dict
            start_to_close_timeout=timedelta(seconds=60),
            schedule_to_close_timeout=timedelta(seconds=90),
            retry_policy=workflow.RetryPolicy(
                initial_interval=timedelta(seconds=2),
                backoff_coefficient=2.0,
                maximum_attempts=3,
            ),
            task_queue="rag-q",
        )

        # Normalize activity output
        if isinstance(chunks_result, dict):
            chunks = chunks_result.get("chunks", [])
        else:
            workflow.logger.warn(
                f"[AnswerWorkflow] retrieve_chunks returned non-dict: {type(chunks_result)}"
            )
            chunks = []

        workflow.logger.info(
            f"[AnswerWorkflow] Retrieved {len(chunks)} chunks"
        )

        # ----------------------------------------------------------------------
        # 2) COMPOSE ANSWER
        # ----------------------------------------------------------------------
        draft_args = {
            "question": question,
            "chunks": chunks,
        }

        draft = await workflow.execute_activity(
            "compose_answer",
            draft_args,                             # MUST be dict
            start_to_close_timeout=timedelta(seconds=60),
            schedule_to_close_timeout=timedelta(seconds=90),
            retry_policy=workflow.RetryPolicy(
                initial_interval=timedelta(seconds=2),
                backoff_coefficient=2.0,
                maximum_attempts=3,
            ),
            task_queue="rag-q",
        )

        # Defensive parse
        if not isinstance(draft, dict):
            workflow.logger.error(
                f"[AnswerWorkflow] compose_answer returned invalid type: {type(draft)}"
            )
            draft = {"answer": "", "citations": []}

        workflow.logger.info(
            "[AnswerWorkflow] Compose step completed"
        )

        # ----------------------------------------------------------------------
        # 3) REDACT
        # ----------------------------------------------------------------------
        red = await workflow.execute_activity(
            "redact_enforce",
            draft,                                   # MUST be dict
            start_to_close_timeout=timedelta(seconds=30),
            schedule_to_close_timeout=timedelta(seconds=60),
            task_queue="rag-q",
        )

        # Normalize output
        answer = red.get("answer", "") if isinstance(red, dict) else ""
        confidence = float(red.get("confidence", 0.0)) if isinstance(red, dict) else 0.0

        workflow.logger.info(
            f"[AnswerWorkflow] Redaction complete | confidence={confidence}"
        )

        # ----------------------------------------------------------------------
        # 4) ROUTE
        # ----------------------------------------------------------------------
        route_args = {
            "answer": answer,
            "confidence": confidence,
            "threshold": threshold,
            "inbound_msg_id": inbound_msg_id,
        }

        route_result = await workflow.execute_activity(
            "route",
            route_args,                               # MUST be dict
            start_to_close_timeout=timedelta(seconds=20),
            schedule_to_close_timeout=timedelta(seconds=30),
            task_queue="rag-q",
        )

        if isinstance(route_result, dict):
            workflow.logger.info(
                f"[AnswerWorkflow] Route complete | result={route_result}"
            )
        else:
            workflow.logger.warn(
                f"[AnswerWorkflow] Route returned non-dict: {type(route_result)}"
            )

        return route_result
