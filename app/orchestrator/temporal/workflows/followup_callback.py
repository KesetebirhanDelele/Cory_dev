# app/orchestrator/temporal/workflows/followup_callback.py

from __future__ import annotations

from dataclasses import dataclass
from temporalio import workflow

from app.orchestrator.temporal.workflows.missed_call_followup import (
    MissedCallFollowupWorkflow,
)


@dataclass
class CallbackFollowupInput:
    """
    Generic input for a callback/voicemail follow-up request.

    This structure is compatible with MissedCallFollowupWorkflow,
    which already handles:
        - delayed SMS
        - delayed call retry
        - delayed email
        - voicemail pathways
        - callback pathways
    """
    enrollment_id: str
    registration_id: str
    campaign_step_id: str
    org_id: str
    project_id: str
    phone: str
    email: str
    intent: str  # e.g. "callback_requested" or "voicemail"


@workflow.defn
class CallbackFollowupWorkflow:
    """
    Thin wrapper workflow.
    Instead of duplicating follow-up logic, this forwards all inputs
    to the existing MissedCallFollowupWorkflow which already manages:

        - timers
        - retry steps
        - voicemail → SMS → call → email sequences
        - campaign step update hooks

    This ensures a single source of truth for follow-up logic.
    """

    @workflow.run
    async def run(self, inp: CallbackFollowupInput) -> None:
        # Forward to the upstream workflow as a child workflow
        return await workflow.execute_child_workflow(
            MissedCallFollowupWorkflow.run,
            inp,
            id=f"callback-followup-{inp.enrollment_id}",
            task_queue="cory-queue",
        )
