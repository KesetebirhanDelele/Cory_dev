# app/orchestrator/temporal/workflows/campaign.py
from __future__ import annotations
from typing import Dict, Any, Optional
from datetime import timedelta
from temporalio import workflow

# Import activities inside unsafe block so Temporal can resolve them in tests
with workflow.unsafe.imports_passed_through():
    from app.orchestrator.temporal.activities.sms_send import sms_send
    from app.orchestrator.temporal.activities.email_send import email_send
    from app.orchestrator.temporal.activities.voice_start import voice_start


@workflow.defn
class CampaignWorkflow:
    """
    Minimal one-step campaign workflow:
      - Executes exactly one activity (chosen by LangGraph's instruction).
      - Waits for a 'provider_event' signal up to a timeout.
      - Returns attempt metadata plus final signal (or timeout).
    """

    def __init__(self) -> None:
        self._event: Optional[Dict[str, Any]] = None

    @workflow.signal
    def provider_event(self, event: Dict[str, Any]) -> None:
        """
        Signal payload example:
          {
            "status": "delivered" | "failed" | ...,
            "provider_ref": "stub-sms-enr_42",
            "data": {...}
          }
        """
        self._event = event

    @workflow.run
    async def run(self, enrollment_id: str, instruction: Dict[str, Any]) -> Dict[str, Any]:
        """
        Args:
          enrollment_id: lead/enrollment identifier from LangGraph.
          instruction: {
            "action": "send_sms" | "send_email" | "voice_start",
            "payload": {...},
            "await_timeout_seconds": int (optional, default 20)
          }
        Returns:
          {
            "attempt": {...activity_result},
            "final": {...signal_payload} | {"status": "timeout", "provider_ref": "..."}
          }
        """
        action = instruction.get("action")
        payload = instruction.get("payload", {})

        # Execute the requested activity
        if action == "send_sms":
            attempt = await workflow.execute_activity(
                sms_send,
                args=[enrollment_id, payload],
                start_to_close_timeout=timedelta(seconds=30),
            )
        elif action == "send_email":
            attempt = await workflow.execute_activity(
                email_send,
                args=[enrollment_id, payload],
                start_to_close_timeout=timedelta(seconds=30),
            )
        elif action == "voice_start":
            attempt = await workflow.execute_activity(
                voice_start,
                args=[enrollment_id, payload],
                start_to_close_timeout=timedelta(seconds=60),
            )
        else:
            raise ValueError(f"Unsupported action: {action}")

        # Await provider_event (or timeout)
        timeout_s = int(instruction.get("await_timeout_seconds", 20))

        # If the signal already arrived (buffered/delivered earlier), return immediately
        if self._event is not None:
            return {"attempt": attempt, "final": self._event}

        got_signal = await workflow.wait_condition(
            lambda: self._event is not None,
            timeout=timedelta(seconds=timeout_s),
        )

        final = self._event if got_signal else {
            "status": "timeout",
            "provider_ref": attempt.get("provider_ref"),
        }
        return {"attempt": attempt, "final": final}
