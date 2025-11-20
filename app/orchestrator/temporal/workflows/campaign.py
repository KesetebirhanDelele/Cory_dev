# app/orchestrator/temporal/workflows/campaign.py

from __future__ import annotations

import os
from datetime import timedelta
from typing import Any, Dict, Optional, Tuple, List

from temporalio import workflow
from temporalio.common import RetryPolicy

from app.policy.guards import pre_send_decision
from app.orchestrator.temporal.common.provider_event import ProviderEvent
from app.orchestrator.temporal.common.instruction import Instruction
from app.orchestrator.temporal.common.attempts import Attempt, AwaitSpec
from app.orchestrator.temporal.common.retry_policies import activity_options_for

# Feature flag (C2.1)
ENABLE_GUARDS = os.getenv("ENABLE_GUARDS", "0") == "1"

# Activities + callback workflow imported safely for Temporal
with workflow.unsafe.imports_passed_through():
    from app.orchestrator.temporal.activities.sms_send import sms_send
    from app.orchestrator.temporal.activities.email_send import email_send
    from app.orchestrator.temporal.activities.voice_start import voice_start
    # 👇 Follow-up callback workflow for voicemail / callback_requested
    try:
        from app.orchestrator.temporal.workflows.followup_callback import (
            CallbackFollowupWorkflow,
            CallbackFollowupInput,
        )
    except Exception:  # pragma: no cover - allows tests without this module
        CallbackFollowupWorkflow = None  # type: ignore[assignment]
        CallbackFollowupInput = None  # type: ignore[assignment]


@workflow.defn
class CampaignWorkflow:
    """
    Multi-step campaign workflow (C3.1)
    - Executes a sequence of steps.
    - Supports branching (on success or failure).
    - Applies quiet hours / consent / frequency guards (C2.1).
    - Waits for provider signals or timeouts.
    """

    def __init__(self) -> None:
        self._event: Optional[Dict[str, Any]] = None
        self.history: List[Dict[str, Any]] = []

    # -------------------
    # Signal handler
    # -------------------
    @workflow.signal
    def provider_event(self, event: Dict[str, Any] | ProviderEvent) -> None:
        """Receives external delivery/failure events."""
        pe = event if isinstance(event, ProviderEvent) else ProviderEvent(**event)
        self._event = pe.model_dump()

    # -------------------
    # Workflow main logic
    # -------------------
    @workflow.run
    async def run(self, campaign_id: str, steps: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Execute a multi-step campaign flow.

        Example:
        [
            {
                "action": "send_email",
                "payload": {...},
                "wait_hours": 1,
                "on_failure": 2
            },
            {
                "action": "send_sms",
                "payload": {...},
                "wait_hours": 2
            },
            {
                "action": "voice_start",
                "payload": {...},
                # Optional: enable callback/voicemail follow-up
                "enable_callback_followup": true,
                "context": {
                    "enrollment_id": "...",
                    "registration_id": "...",
                    "campaign_step_id": "...",
                    "org_id": "...",
                    "project_id": "...",
                    "phone": "+1555...",
                    "email": "lead@example.com"
                }
            }
        ]
        """
        step_index = 0
        total_steps = len(steps)

        while 0 <= step_index < total_steps:
            step = steps[step_index]
            action = step.get("action")
            payload = step.get("payload", {})
            wait_hours = float(step.get("wait_hours", 0.0))
            context: Dict[str, Any] = step.get("context", {}) or {}

            # --------------------
            # Pre-send Guards (C2.1)
            # --------------------
            if ENABLE_GUARDS:
                enrollment = step.get("enrollment", {})
                policy = step.get("policy", {})

                verdict = pre_send_decision(
                    enrollment=enrollment,
                    step={"channel": step.get("channel", _infer_channel(action))},
                    policy=policy,
                    context=context,
                )
                if not verdict.get("allow", True):
                    self.history.append(
                        {
                            "step": step_index,
                            "action": action,
                            "status": "guard_block",
                            "reason": verdict.get("reason"),
                            "next_hint": verdict.get("next_hint"),
                        }
                    )
                    step_index += 1
                    continue

            # --------------------
            # Execute Activity
            # --------------------
            activity_fn = _get_activity(action)
            opts, rp = activity_options_for(_infer_channel(action))
            attempt_result: Dict[str, Any]

            try:
                if in_workflow_env():
                    attempt_result = await workflow.execute_activity(
                        activity_fn,
                        args=[campaign_id, payload],
                        retry_policy=rp,
                        **opts,
                    )
                else:
                    # Local mode (pytest)
                    attempt_result = await activity_fn(campaign_id, payload)
            except Exception as e:
                self.history.append(
                    {
                        "step": step_index,
                        "action": action,
                        "status": "activity_error",
                        "error": str(e),
                    }
                )
                # Jump to fallback if defined
                if "on_failure" in step:
                    step_index = step["on_failure"]
                    continue
                else:
                    break

            # --------------------
            # Wait for Signal or Timeout
            # --------------------
            timeout_s = int(step.get("await_timeout_seconds", 20))
            self._event = None

            if in_workflow_env():
                got_signal = await workflow.wait_condition(
                    lambda: self._event is not None,
                    timeout=timedelta(seconds=timeout_s),
                )
            else:
                got_signal = False  # no signal in local test mode

            final_event = self._event if got_signal else {"status": "timeout"}
            final_status = final_event.get("status")

            self.history.append(
                {
                    "step": step_index,
                    "action": action,
                    "attempt": attempt_result,
                    "final": final_event,
                }
            )

            # ------------------------------------------------------
            # 🔀 Branch: callback / voicemail → start follow-up workflow
            # ------------------------------------------------------
            # Intent can come from provider_event.data["intent"], or be injected
            # into the step context as a fallback.
            data = final_event.get("data") or {}
            intent = (
                data.get("intent")
                or final_event.get("intent")
                or context.get("intent")
            )

            if (
                in_workflow_env()
                and CallbackFollowupWorkflow is not None
                and CallbackFollowupInput is not None
                and step.get("enable_callback_followup")
                and intent in ("callback_requested", "voicemail")
            ):
                enrollment_id = context.get("enrollment_id")
                registration_id = context.get("registration_id")
                campaign_step_id = context.get("campaign_step_id")
                org_id = context.get("org_id")
                project_id = context.get("project_id")
                phone = context.get("phone")
                email = context.get("email")

                # Only start follow-up workflow if we have the core IDs
                if enrollment_id and registration_id and campaign_step_id:
                    await workflow.start_child_workflow(
                        CallbackFollowupWorkflow.run,
                        CallbackFollowupInput(
                            enrollment_id=enrollment_id,
                            registration_id=registration_id,
                            campaign_step_id=campaign_step_id,
                            org_id=org_id,
                            project_id=project_id,
                            phone=phone,
                            email=email,
                            intent=intent,
                        ),
                        id=f"callback-followup-{enrollment_id}",
                    )
                    # Record branch + stop this campaign workflow
                    self.history.append(
                        {
                            "step": step_index,
                            "action": action,
                            "status": "callback_followup_started",
                            "intent": intent,
                        }
                    )
                    break

            # --------------------
            # Branch on failure
            # --------------------
            if final_status not in ("delivered", "completed", "replied", "sent"):
                if "on_failure" in step:
                    step_index = step["on_failure"]
                    continue

            # Wait between steps if defined
            if wait_hours > 0 and in_workflow_env():
                await workflow.sleep(timedelta(hours=wait_hours))

            step_index += 1

        return {"campaign_id": campaign_id, "history": self.history}


# ---------------------------
# Deterministic Planner (C1.1)
# ---------------------------

def plan_single_step(
    instruction: Instruction, state: dict | None = None
) -> Tuple[Attempt, AwaitSpec]:
    """Translate Instruction → deterministic Temporal plan."""
    _ = state or {}

    expected_event = {
        "SendSMS": "delivered",
        "SendEmail": "delivered",
        "StartCall": "delivered",
    }.get(instruction.action, "delivered")

    await_spec = AwaitSpec(
        expect=expected_event,
        timeout_seconds=instruction.await_timeout_seconds or 30,
        on_timeout="timeout",
    )
    attempt = Attempt(action=instruction.action, params=instruction.payload)

    return attempt, await_spec


# ---------------------------
# Helper functions
# ---------------------------

def _infer_channel(action: str) -> str:
    """Infer communication channel from action string."""
    if "sms" in action.lower():
        return "sms"
    if "email" in action.lower():
        return "email"
    if "voice" in action.lower() or "call" in action.lower():
        return "voice"
    return "unknown"


def _get_activity(action: str):
    """Map action name to Temporal activity."""
    if action == "send_sms":
        return sms_send
    elif action == "send_email":
        return email_send
    elif action == "voice_start":
        return voice_start
    raise ValueError(f"Unsupported action: {action}")


def in_workflow_env() -> bool:
    """Detect if running inside Temporal workflow environment."""
    try:
        return workflow.in_workflow()
    except Exception:
        return False
