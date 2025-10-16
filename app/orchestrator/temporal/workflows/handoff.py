# app/orchestrator/temporal/workflows/handoff.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from app.orchestrator.temporal.activities.handoff_create import (
        create_handoff,
        resolve_handoff_rpc,
        mark_timed_out,
    )

@dataclass
class HandoffInput:
    workflow_run_id: Optional[str]
    subject: str
    channel: str
    payload: Dict[str, Any]
    timeout_seconds: int = 600
    created_by: Optional[str] = None
    assignee: Optional[str] = None
    organization_id: str | None = None   # <-- add this

@dataclass
class HandoffResult:
    handoff_id: str
    outcome: str
    resolution_payload: Dict[str, Any]

@workflow.defn
class HandoffWorkflow:
    def __init__(self) -> None:
        self._resolved = False
        self._resolution_payload: Dict[str, Any] = {}
        self._handoff_id: Optional[str] = None

    @workflow.signal
    async def resolve(self, resolution_payload: Dict[str, Any]):
        if not self._resolved:
            self._resolved = True
            self._resolution_payload = resolution_payload or {}

    @workflow.run
    async def run(self, data: HandoffInput) -> HandoffResult:
        self._handoff_id = await workflow.execute_activity(
            create_handoff,
            {
                "workflow_run_id": data.workflow_run_id,
                "subject": data.subject,
                "channel": data.channel,
                "payload": data.payload or {},
                "timeout_seconds": data.timeout_seconds,
                "created_by": data.created_by,
                "assignee": data.assignee,
            },
            start_to_close_timeout=workflow.timedelta(seconds=20),
        )

        resolved = await workflow.wait_condition(
            lambda: self._resolved,
            timeout=workflow.timedelta(seconds=data.timeout_seconds),
        )

        if resolved:
            await workflow.execute_activity(
                resolve_handoff_rpc,
                {"handoff_id": self._handoff_id, "resolution_payload": self._resolution_payload},
                start_to_close_timeout=workflow.timedelta(seconds=20),
            )
            outcome = "resolved"
        else:
            await workflow.execute_activity(
                mark_timed_out,
                {"handoff_id": self._handoff_id},
                start_to_close_timeout=workflow.timedelta(seconds=20),
            )
            outcome = "timed_out"

        return HandoffResult(
            handoff_id=self._handoff_id,
            outcome=outcome,
            resolution_payload=self._resolution_payload,
        )
