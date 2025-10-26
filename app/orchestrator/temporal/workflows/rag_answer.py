from temporalio import workflow
from datetime import timedelta

@workflow.defn
class AnswerBuilderWf:
    @workflow.run
    async def run(self, question: str, inbound_msg_id: str, threshold: float):
        # 1) retrieve
        chunks = await workflow.execute_activity(
            "retrieve_chunks",  # or the function ref if you use that
            question,
            start_to_close_timeout=timedelta(seconds=60),
            schedule_to_close_timeout=timedelta(seconds=90),
            retry_policy=workflow.RetryPolicy(
                initial_interval=timedelta(seconds=2),
                backoff_coefficient=2.0,
                maximum_attempts=3,
            ),
            task_queue="rag-q",
        )

        # 2) compose
        draft = await workflow.execute_activity(
            "compose_answer",
            {"question": question, "chunks": chunks},
            start_to_close_timeout=timedelta(seconds=60),
            schedule_to_close_timeout=timedelta(seconds=90),
            retry_policy=workflow.RetryPolicy(
                initial_interval=timedelta(seconds=2),
                backoff_coefficient=2.0,
                maximum_attempts=3,
            ),
            task_queue="rag-q",
        )

        # 3) redact
        red = await workflow.execute_activity(
            "redact_enforce",
            draft,
            start_to_close_timeout=timedelta(seconds=30),
            schedule_to_close_timeout=timedelta(seconds=60),
            task_queue="rag-q",
        )

        # 4) route
        return await workflow.execute_activity(
            "route",
            {"answer": red["answer"], "confidence": red["confidence"], "threshold": threshold,
             "inbound_msg_id": inbound_msg_id},
            start_to_close_timeout=timedelta(seconds=20),
            schedule_to_close_timeout=timedelta(seconds=30),
            task_queue="rag-q",
        )
