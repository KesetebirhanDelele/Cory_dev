# app/orchestrator/temporal/workflows/campaign.py
from __future__ import annotations

import os
from datetime import timedelta
from typing import Any, Dict, Optional, Tuple

from temporalio import workflow
from temporalio.common import RetryPolicy

from app.policy.guards import pre_send_decision
from app.orchestrator.temporal.common.provider_event import ProviderEvent
from app.orchestrator.temporal.common.instruction import Instruction
from app.orchestrator.temporal.common.attempts import Attempt, AwaitSpec
from app.orchestrator.temporal.common.retry_policies import activity_options_for

# Feature flag: OFF by default (so existing tests remain green without policy checks)
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
        Signal payload (validated against ProviderEvent):

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
            "policy": {...},          # e.g., quiet_hours/min_gap/dnc settings
            "enrollment": {...},      # e.g., {"timezone": "America/Chicago", "labels": ["dnc"], "consent": true}
            "step": {...},            # e.g., {"channel": "sms"}
            "context": {...},         # e.g., {"last_sent_at": "...", "now": "...", "sent_count_last_24h": 0}
          }

        Returns:
          {
            "attempt": {...activity_result} | None,
            "final": {...signal_payload} | {"status": "timeout" | "guard_block", ...}
          }
        """
        action = (instruction or {}).get("action")
        payload = (instruction or {}).get("payload", {})

        # ---- Guard check (behind feature flag) -------------------------------
        if ENABLE_GUARDS:
            enrollment = instruction.get("enrollment") or {}
            step = instruction.get("step") or {
                "channel": ("sms" if action == "send_sms"
                            else "email" if action == "send_email"
                            else "voice")
            }
            policy = instruction.get("policy") or {}
            context = instruction.get("context") or {}

            verdict = pre_send_decision(
                enrollment=enrollment,
                step=step,
                policy=policy,
                context=context,
            )
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

        # ---- Execute the requested activity (with retry policy) -------------
        # Centralized options per channel (timeouts, backoff, non-retryables)
        attempt: Dict[str, Any]
        if action == "send_sms":
            opts, rp = activity_options_for("sms")
            attempt = await workflow.execute_activity(
                sms_send,
                args=[enrollment_id, payload],
                retry_policy=rp,
                **opts,
            )
        elif action == "send_email":
            opts, rp = activity_options_for("email")
            attempt = await workflow.execute_activity(
                email_send,
                args=[enrollment_id, payload],
                retry_policy=rp,
                **opts,
            )
        elif action == "voice_start":
            opts, rp = activity_options_for("voice")
            attempt = await workflow.execute_activity(
                voice_start,
                args=[enrollment_id, payload],
                retry_policy=rp,
                **opts,
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


# ---------------------------
# Deterministic planner (C1.1)
# ---------------------------

def plan_single_step(instruction: Instruction, state: dict | None = None) -> Tuple[Attempt, AwaitSpec]:
    """
    Deterministic single-step planner:
      - Translates Instruction -> Attempt
      - Declares what provider_event we will await next (AwaitSpec)
    No side effects; no randomness; depends only on arguments.
    """
    _ = state or {}

    # Map semantic action → expected provider event (deterministic defaults)
    expected_event = {
        "SendSMS": "delivered",
        "SendEmail": "delivered",
        "StartCall": "delivered",  # success path implies call completed
    }.get(instruction.action, "delivered")

    attempt = Attempt(action=instruction.action, params=instruction.payload)

    await_spec = AwaitSpec(
        expect=expected_event,                   # what success looks like for this action
        timeout_seconds=instruction.await_timeout_seconds or 30,
        on_timeout="timeout",
    )

    return attempt, await_spec
