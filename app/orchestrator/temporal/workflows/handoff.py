# app/orchestrator/temporal/workflows/handoff.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import timedelta
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from app.orchestrator.temporal.activities.handoff_create import (
        create_handoff,
        resolve_handoff_rpc,
        mark_timed_out,
    )

# -------- Types --------
@dataclass
class HandoffInput:
    workflow_run_id: Optional[str]
    subject: str
    channel: str
    payload: Dict[str, Any]
    timeout_seconds: int = 600
    created_by: Optional[str] = None
    assignee: Optional[str] = None
    organization_id: Optional[str] = None  # keep as Optional[str] for consistency

@dataclass
class HandoffResult:
    handoff_id: str
    outcome: str                 # "resolved" | "timed_out"
    resolution_payload: Dict[str, Any]


# -------- Workflow --------
@workflow.defn
class HandoffWorkflow:
    def __init__(self) -> None:
        self._resolved: bool = False
        self._resolution_payload: Dict[str, Any] = {}
        self._handoff_id: Optional[str] = None
        self._log = workflow.logger

    @workflow.signal(name="resolve")
    def resolve(
        self,
        resolution_payload: Optional[Dict[str, Any]] = None,
        *,
        decision: Optional[str] = None,
        by: Optional[str] = None,
    ) -> None:
        """
        Accepts either:
          - a single dict: {"decision": "...", "by": "...", ...}
          - or named kwargs: decision="...", by="..."
        """
        payload = resolution_payload or {}
        merged = {**payload}
        if decision is not None:
            merged["decision"] = decision
        if by is not None:
            merged["by"] = by

        if not self._resolved:
            self._resolved = True
            self._resolution_payload = merged
            self._log.info("Signal 'resolve' received: %s", self._resolution_payload)
        else:
            self._log.info("Signal 'resolve' received again; ignoring (already resolved).")

    @workflow.run
    async def run(self, data: HandoffInput) -> HandoffResult:
        self._log.info(
            "HandoffWorkflow start | run_id=%s subject=%s channel=%s timeout=%ss org=%s",
            data.workflow_run_id, data.subject, data.channel, data.timeout_seconds, data.organization_id
        )

        # Create handoff record via activity (now includes organization_id)
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
                "organization_id": data.organization_id,
            },
            start_to_close_timeout=workflow.timedelta(seconds=20),
        )
        self._log.info("Created handoff_id=%s", self._handoff_id)

        # Wait for resolve signal with timeout (use datetime.timedelta)
        timeout_td = timedelta(seconds=data.timeout_seconds)
        self._log.info("Waiting for resolve up to %s", timeout_td)

        resolved = await workflow.wait_condition(
            lambda: self._resolved,
            timeout=timeout_td,
        )

        # Guard: some SDK/env mixes may return False immediately even if flag is set;
        # trust the authoritative flag to avoid false timeouts.
        if not resolved and self._resolved:
            self._log.info("wait_condition returned False but _resolved=True; treating as resolved")
            resolved = True

        if resolved:
            self._log.info("Resolved before timeout; applying resolution via RPC")
            await workflow.execute_activity(
                resolve_handoff_rpc,
                {"handoff_id": self._handoff_id, "resolution_payload": self._resolution_payload},
                start_to_close_timeout=workflow.timedelta(seconds=20),
            )
            outcome = "resolved"
        else:
            self._log.info("Timed out after %s seconds; marking as timed_out", data.timeout_seconds)
            await workflow.execute_activity(
                mark_timed_out,
                {"handoff_id": self._handoff_id},
                start_to_close_timeout=workflow.timedelta(seconds=20),
            )
            outcome = "timed_out"

        return HandoffResult(
            handoff_id=self._handoff_id or "",
            outcome=outcome,
            resolution_payload=self._resolution_payload,
        )
