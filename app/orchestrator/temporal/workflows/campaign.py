# app/orchestrator/temporal/workflows/campaign.py
from __future__ import annotations
import os
from typing import Dict, Any, Optional
from datetime import timedelta
from temporalio import workflow

from app.orchestrator.temporal.common.provider_event import ProviderEvent
from app.policy.guards import pre_send_decision  # <- guards

from typing import Tuple
from app.orchestrator.temporal.common.instruction import Instruction
from app.orchestrator.temporal.common.attempts import Attempt, AwaitSpec

# Feature flag: OFF by default (so existing tests remain green)
ENABLE_GUARDS = os.getenv("ENABLE_GUARDS", "0") == "1"

# Import activities inside unsafe block so Temporal can resolve them in tests
with workflow.unsafe.imports_passed_through():
    from app.orchestrator.temporal.activities.sms_send import sms_send
    from app.orchestrator.temporal.activities.email_send import email_send
    from app.orchestrator.temporal.activities.voice_start import voice_start


@workflow.defn
class CampaignWorkflow:
    """
    Minimal one-step campaign workflow:
      - Optionally runs guards (quiet hours / consent / min-gap) before sending.
      - Executes exactly one activity (chosen by LangGraph's instruction).
      - Waits for a 'provider_event' signal up to a timeout.
      - Returns attempt metadata plus final signal (or timeout / guard_block).
    """

    def __init__(self) -> None:
        self._event: Optional[Dict[str, Any]] = None

    @workflow.signal
    def provider_event(self, event: Dict[str, Any] | ProviderEvent) -> None:
        """
        Signal payload example:
          {
            "status": "delivered" | "failed" | "replied" | "completed" | "bounced" | "queued",
            "provider_ref": "stub-sms-enr_42",
            "channel": "sms" | "email" | "voice",
            "activity_id": "<uuid>",
            "data": {...}
          }
        """
        pe = event if isinstance(event, ProviderEvent) else ProviderEvent(**event)
        # Store as plain dict for JSON-safe returns
        self._event = pe.model_dump()

    @workflow.run
    async def run(self, enrollment_id: str, instruction: Dict[str, Any]) -> Dict[str, Any]:
        """
        Args:
          enrollment_id: lead/enrollment identifier from LangGraph.
          instruction: {
            "action": "send_sms" | "send_email" | "voice_start",
            "payload": {...},
            "await_timeout_seconds": int (optional, default 20),

            # Optional (used only when ENABLE_GUARDS=1)
            "policy": {...},          # campaign policy subset (quiet_hours, min_gap_minutes, dnc_labels, timezone_field, etc.)
            "enrollment": {...},      # e.g., {"timezone": "America/Chicago", "labels": ["dnc"]}
            "step": {...},            # e.g., {"channel": "sms"}
            "context": {...},         # e.g., {"last_sent_at": "...", "now": datetime-iso}
          }
        Returns:
          {
            "attempt": {...activity_result} | None,
            "final": {...signal_payload} | {"status": "timeout" | "guard_block", ...}
          }
        """
        action = instruction.get("action")
        payload = instruction.get("payload", {})

        # ---- Guard check (behind feature flag) -------------------------------
        if ENABLE_GUARDS:
            enrollment = instruction.get("enrollment") or {}
            step = instruction.get("step") or {"channel": ("sms" if action == "send_sms"
                                                           else "email" if action == "send_email"
                                                           else "voice")}
            policy = instruction.get("policy") or {}
            context = instruction.get("context") or {}
            verdict = pre_send_decision(enrollment=enrollment, step=step, policy=policy, context=context)
            if not verdict.get("allow", True):
                # Skip sending; return a clear structured outcome
                return {
                    "attempt": None,
                    "final": {
                        "status": "guard_block",
                        "reason": verdict.get("reason"),
                        "next_hint": verdict.get("next_hint"),
                    },
                }

        # ---- Execute the requested activity ---------------------------------
        if action == "send_sms":
            attempt = await workflow.execute_activity(
                sms_send,
                args=[enrollment_id, payload],
                start_to_close_timeout=timedelta(seconds=30),  # keep generous S2C for network variance
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

        # ---- Await provider_event (or timeout) -------------------------------
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

# app/orchestrator/temporal/workflows/campaign.py  (APPEND THESE LINES)

def plan_single_step(instruction: Instruction, state: dict | None = None) -> Tuple[Attempt, AwaitSpec]:
    """
    Deterministic single-step planner:
      - Translates Instruction -> Attempt
      - Declares what provider_event we will await next (AwaitSpec)
    No side effects; no randomness; depends only on arguments.
    """
    state = state or {}

    # Map semantic action → expected provider event (deterministic defaults)
    # You can extend this table as you add actions/channels.
    expected_event = {
        "SendSMS": "delivered",
        "SendEmail": "delivered",
        "StartCall": "delivered",  # success path means contact answered & completed
    }.get(instruction.action, "delivered")

    attempt = Attempt(action=instruction.action, params=instruction.payload)

    await_spec = AwaitSpec(
        expect=expected_event,                   # what success looks like for this action
        timeout_seconds=instruction.await_timeout_seconds or 30,
        on_timeout="timeout",
    )

    return attempt, await_spec
