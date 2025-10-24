# app/orchestrator/temporal/workflows/answer_builder.py

from datetime import timedelta
from temporalio import workflow
from app.orchestrator.temporal.activities.rag_compose import compose_answer  # or your actual answer builder activity

@workflow.defn
class AnswerWorkflow:
    """Temporal workflow to coordinate the answer-building process."""

    @workflow.run
    async def run(self, query: str, inbound_id: str, threshold: float):
        result = await workflow.execute_activity(
            compose_answer,
            args=[query, inbound_id, threshold],
            start_to_close_timeout=timedelta(seconds=120),  # longer timeout
            schedule_to_close_timeout=timedelta(minutes=5),
        )
        return result
