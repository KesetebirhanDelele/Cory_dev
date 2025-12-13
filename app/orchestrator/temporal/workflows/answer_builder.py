# app/orchestrator/temporal/workflows/answer_builder.py
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List

from temporalio import workflow

# ✅ Heavy imports passed through (bypass Temporal sandbox limits)
with workflow.unsafe.imports_passed_through():
    # RAG pipeline activities
    from app.orchestrator.temporal.activities.rag import retrieve_chunks
    from app.orchestrator.temporal.activities.rag_compose import compose_answer
    from app.orchestrator.temporal.activities.rag_redact import redact_enforce
    from app.orchestrator.temporal.activities.rag_route import route

    # SMS helpers
    from app.orchestrator.temporal.activities.sms_send import sms_send
    from app.orchestrator.temporal.activities.sms_summarize import (
        sms_summarize_answer,
    )


class _Event:
    """Deterministic async event replacement for Temporal workflows."""

    def __init__(self) -> None:
        self._flag = False

    def set(self) -> None:
        self._flag = True

    def clear(self) -> None:
        self._flag = False

    async def wait(self) -> None:
        await workflow.wait_condition(lambda: self._flag)


@workflow.defn(name="AnswerWorkflow")
class AnswerWorkflow:
    """Workflow for RAG-based SMS conversation."""

    def __init__(self) -> None:
        # All inbound SMS payloads for this thread
        self.messages: List[Dict[str, Any]] = []
        self._new_message_event = _Event()

    # ------------------------------------------------------------------
    # 📩 SMS Signal Handler
    # ------------------------------------------------------------------
    @workflow.signal
    async def sms_inbound_signal(self, payload: Dict[str, Any]) -> None:
        """
        Handle inbound SMS from webhook.

        Expected payload (from sms_query_handler):
            {
                "from": "+15551234567",
                "to": "+1....",
                "body": "text from user",
                "inbound_id": "provider msg id",
                ...
            }
        """
        from_number = payload.get("from")
        body = payload.get("body")
        workflow.logger.info("📩 Received SMS from %s: %s", from_number, body)
        self.messages.append(payload)
        self._new_message_event.set()

    # ------------------------------------------------------------------
    # 🧠 Helper: run RAG (retrieve → compose → redact)
    # ------------------------------------------------------------------
    async def _build_answer(
        self,
        question: str,
        threshold: float,
    ) -> Dict[str, Any]:
        """
        Run the RAG pipeline (retrieve → compose → redact)
        and return the final answer payload.

        Returns:
            {
                "answer": str,
                "confidence": float,
            }
        """
        workflow.logger.info("🧠 RAG pipeline start | question=%s", question)

        # 1️⃣ Retrieve candidate chunks
        retrieve_input: Dict[str, Any] = {
            "query": question,
            "threshold": float(threshold),
        }
        retrieve_result: Dict[str, Any] = await workflow.execute_activity(
            retrieve_chunks,
            retrieve_input,  # ONE dict arg
            start_to_close_timeout=timedelta(seconds=60),
        )
        chunks: List[Dict[str, Any]] = retrieve_result.get("chunks", [])

        # 2️⃣ Compose answer
        compose_input: Dict[str, Any] = {
            "question": question,
            "chunks": chunks,
        }
        compose_result: Dict[str, Any] = await workflow.execute_activity(
            compose_answer,
            compose_input,
            start_to_close_timeout=timedelta(seconds=60),
        )
        initial_answer: str = compose_result.get("answer", "")

        # 3️⃣ Redact
        redact_input: Dict[str, Any] = {"answer": initial_answer}
        redacted_result: Dict[str, Any] = await workflow.execute_activity(
            redact_enforce,
            redact_input,
            start_to_close_timeout=timedelta(seconds=30),
        )
        final_answer: str = redacted_result.get("answer", initial_answer)
        confidence: float = float(redacted_result.get("confidence", 0.0))

        return {
            "answer": final_answer,
            "confidence": confidence,
        }

    # ------------------------------------------------------------------
    # 🧠 Main Workflow Logic
    # ------------------------------------------------------------------
    @workflow.run
    async def run(
        self,
        query: str,
        from_number: str,
        inbound_id: str,
        threshold: float,
    ) -> Dict[str, Any]:
        """
        Main conversation loop:

        - Build answer for the first query (RAG) and summarize for SMS.
        - Route to outbox / handoff with intent + next_action.
        - Then wait for new SMS signals and do the same for each follow-up.
        """
        workflow.logger.info(
            "🧠 Starting AnswerWorkflow | from=%s | query=%s",
            from_number,
            query,
        )

        # ==============================================================
        # 1️⃣ INITIAL MESSAGE
        # ==============================================================

        # Run RAG pipeline (no routing yet)
        rag_result = await self._build_answer(query, threshold)
        rag_answer = rag_result["answer"]
        rag_confidence = float(rag_result.get("confidence", 0.0))

        # Summarize for SMS + classify intent / next_action
        sms_summary = await workflow.execute_activity(
            sms_summarize_answer,
            {
                "question": query,
                "answer": rag_answer,
                "history": self.messages,
                # SMS-safe length well below Twilio concat limit
                "max_chars": 480,
            },
            start_to_close_timeout=timedelta(seconds=30),
        )

        sms_body: str = sms_summary.get("sms_text") or rag_answer
        intent: str = sms_summary.get("intent") or "other"
        next_action: str = sms_summary.get("next_action") or "answer_only"

        workflow.logger.info(
            "🧠 Initial SMS summary | intent=%s | next_action=%s | confidence=%.2f",
            intent,
            next_action,
            rag_confidence,
        )

        # 4️⃣ Route to outbox / handoff with intent + next_action
        route_input: Dict[str, Any] = {
            "answer": rag_answer,
            "inbound_msg_id": inbound_id,
            "confidence": rag_confidence,
            "threshold": float(threshold),
            "intent": intent,
            "next_action": next_action,
        }
        await workflow.execute_activity(
            route,
            route_input,
            start_to_close_timeout=timedelta(seconds=30),
        )

        # Optional tweak for handoff: make SMS mention advisor if LLM recommended
        if next_action == "handoff_to_human" or rag_confidence < threshold:
            if "advisor" not in sms_body.lower():
                sms_body = (
                    sms_body.rstrip()
                    + " I can connect you with an admissions advisor for more details."
                )

        # Send initial SMS reply
        await workflow.execute_activity(
            sms_send,
            {"to": from_number, "body": sms_body},
            start_to_close_timeout=timedelta(seconds=30),
        )
        workflow.logger.info("📤 Initial RAG/SMS answer sent to %s", from_number)

        # ==============================================================
        # 2️⃣ CONVERSATION LOOP – handle follow-up SMS
        # ==============================================================
        workflow.logger.info("✅ Waiting for follow-up SMS...")
        result: Dict[str, Any] = {
            "last_answer": rag_answer,
            "last_intent": intent,
            "last_next_action": next_action,
            "last_confidence": rag_confidence,
        }

        while True:
            await self._new_message_event.wait()
            self._new_message_event.clear()

            latest = self.messages[-1]
            follow_from = latest.get("from")
            follow_body = (latest.get("body") or "").strip()

            workflow.logger.info(
                "💬 Received follow-up SMS from %s: '%s'",
                follow_from,
                follow_body,
            )

            if not follow_body:
                # Ignore empty follow-ups and continue waiting
                continue

            # Run RAG again for the follow-up question
            follow_rag = await self._build_answer(
                follow_body,
                threshold,
            )
            follow_answer = follow_rag["answer"]
            follow_confidence = float(follow_rag.get("confidence", 0.0))

            # Summarize + classify again
            follow_summary = await workflow.execute_activity(
                sms_summarize_answer,
                {
                    "question": follow_body,
                    "answer": follow_answer,
                    "history": self.messages,
                    "max_chars": 480,
                },
                start_to_close_timeout=timedelta(seconds=30),
            )

            follow_sms_body: str = follow_summary.get("sms_text") or follow_answer
            follow_intent: str = follow_summary.get("intent") or "other"
            follow_next_action: str = (
                follow_summary.get("next_action") or "answer_only"
            )

            workflow.logger.info(
                "🧠 Follow-up SMS summary | intent=%s | next_action=%s | confidence=%.2f",
                follow_intent,
                follow_next_action,
                follow_confidence,
            )

            # Route again with updated intent / next_action
            follow_route_input: Dict[str, Any] = {
                "answer": follow_answer,
                "inbound_msg_id": inbound_id,  # same conversation/thread id
                "confidence": follow_confidence,
                "threshold": float(threshold),
                "intent": follow_intent,
                "next_action": follow_next_action,
            }
            await workflow.execute_activity(
                route,
                follow_route_input,
                start_to_close_timeout=timedelta(seconds=30),
            )

            if follow_next_action == "handoff_to_human" or follow_confidence < threshold:
                if "advisor" not in follow_sms_body.lower():
                    follow_sms_body = (
                        follow_sms_body.rstrip()
                        + " I can connect you with an admissions advisor for more details."
                    )

            await workflow.execute_activity(
                sms_send,
                {"to": follow_from, "body": follow_sms_body},
                start_to_close_timeout=timedelta(seconds=30),
            )
            workflow.logger.info("📤 Sent follow-up RAG/SMS answer to %s", follow_from)

            # Keep last result in case caller inspects workflow completion later
            result = {
                "last_answer": follow_answer,
                "last_intent": follow_intent,
                "last_next_action": follow_next_action,
                "last_confidence": follow_confidence,
            }

        # (Unreachable, but kept for API completeness)
        return result  # pragma: no cover
