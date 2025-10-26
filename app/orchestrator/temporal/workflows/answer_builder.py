# app/orchestrator/temporal/workflows/answer_builder.py
from __future__ import annotations
from datetime import timedelta
from typing import Any, Dict, List
from temporalio import workflow

# ✅ Heavy imports passed through (bypass Temporal sandbox limits)
with workflow.unsafe.imports_passed_through():
    from app.orchestrator.temporal.activities.rag_retrieve import retrieve_chunks
    from app.orchestrator.temporal.activities.rag_redact import redact_enforce
    from app.orchestrator.temporal.activities.rag_compose import compose_answer
    from app.orchestrator.temporal.activities.sms_send import sms_send  # ✅ added import


class _Event:
    """Deterministic async event replacement for Temporal workflows."""
    def __init__(self):
        self._flag = False

    def set(self):
        self._flag = True

    def clear(self):
        self._flag = False

    async def wait(self):
        await workflow.wait_condition(lambda: self._flag)


@workflow.defn(name="AnswerWorkflow")
class AnswerWorkflow:
    """Workflow for RAG + SMS signal loop."""

    def __init__(self):
        self.messages: List[Dict[str, Any]] = []
        self._new_message_event = _Event()  # ✅ works in Temporal sandbox

    # ----------------------------------------------------------------------
    # 📩 SMS Signal Handler
    # ----------------------------------------------------------------------
    @workflow.signal
    async def sms_inbound_signal(self, payload: Dict[str, Any]):
        """Handle inbound SMS from webhook."""
        from_number = payload.get("from")
        body = payload.get("body")
        workflow.logger.info(f"📩 Received SMS from {from_number}: {body}")
        self.messages.append(payload)
        self._new_message_event.set()

        # ✅ Auto-respond immediately via sms_send activity
        try:
            await workflow.execute_activity(
                sms_send,
                args=[from_number, f"🤖 Thanks for your message: '{body}' — we’ll get back to you shortly!"],
                start_to_close_timeout=timedelta(seconds=15),
            )
            workflow.logger.info(f"📤 Auto-response sent to {from_number}")
        except Exception as e:
            workflow.logger.warning(f"⚠️ Failed to send auto-response: {e}")

    # ----------------------------------------------------------------------
    # 🧠 Main Workflow Logic
    # ----------------------------------------------------------------------
    @workflow.run
    async def run(self, query: str, inbound_id: str, threshold: float):
        workflow.logger.info("🧠 Starting AnswerWorkflow | query=%s", query)

        # 1️⃣ Retrieve candidate chunks
        chunks = await workflow.execute_activity(
            retrieve_chunks,
            args=[query, inbound_id, threshold],
            start_to_close_timeout=timedelta(seconds=60),
        )

        # 2️⃣ Apply redaction rules
        redacted = await workflow.execute_activity(
            redact_enforce,
            args=[chunks],
            start_to_close_timeout=timedelta(seconds=30),
        )

        # 3️⃣ Compose initial answer
        result = await workflow.execute_activity(
            compose_answer,
            args=[{"question": query, "chunks": redacted}],
            start_to_close_timeout=timedelta(seconds=60),
        )

        workflow.logger.info("✅ Initial answer ready; waiting for new SMS...")

        # 4️⃣ Stay alive to receive SMS signals indefinitely
        while True:
            await self._new_message_event.wait()
            self._new_message_event.clear()

            latest = self.messages[-1]
            from_number = latest.get("from")
            body = latest.get("body")
            workflow.logger.info(f"💬 Received follow-up SMS from {from_number}: '{body}'")

            # You could re-run RAG or send another reply here.
            # For now, just acknowledge the follow-up.
            try:
                await workflow.execute_activity(
                    sms_send,
                    args=[from_number, f"📨 Got your follow-up: '{body}' — thanks!"],
                    start_to_close_timeout=timedelta(seconds=15),
                )
            except Exception as e:
                workflow.logger.warning(f"⚠️ Could not send follow-up response: {e}")

        # (Unreachable, but good practice)
        return result
