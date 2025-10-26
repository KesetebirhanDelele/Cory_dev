# app/orchestrator/temporal/workflows/handoff.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import timedelta
from temporalio import workflow

from app.common.tracing import set_trace_id  # (optional for future, not required here)
from datetime import timedelta

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
        self._trace_id: Optional[str] = None          # NEW
        self._log = workflow.logger

    @workflow.signal(name="resolve")
    def resolve(
        self,
        resolution_payload: Optional[Dict[str, Any]] = None,
        *,
        decision: Optional[str] = None,
        by: Optional[str] = None,
        trace_id: Optional[str] = None,              # NEW: allow trace in signal
    ) -> None:
        payload = resolution_payload or {}
        merged = {**payload}
        if decision is not None:
            merged["decision"] = decision
        if by is not None:
            merged["by"] = by
        if trace_id:
            self._trace_id = trace_id                # capture from signal if provided

        if not self._resolved:
            self._resolved = True
            self._resolution_payload = merged
            self._log.info("Signal 'resolve' received: %s", self._resolution_payload)
        else:
            self._log.info("Signal 'resolve' received again; ignoring (already resolved).")

    @workflow.run
    async def run(self, data: HandoffInput) -> HandoffResult:
        # 🧩 extract trace_id from start headers (Temporal header values are bytes)
        start_headers = workflow.info().headers or {}
        if b"trace_id" in start_headers:
            try:
                self._trace_id = start_headers[b"trace_id"].decode("utf-8", "ignore")
            except Exception:
                self._trace_id = None

        # NEW: fallback to input payload for older SDKs
        if not self._trace_id:
            try:
                self._trace_id = (data.payload or {}).get("trace_id")
            except Exception:
                self._trace_id = None

        self._log.info(
            "HandoffWorkflow start | run_id=%s subject=%s channel=%s timeout=%ss org=%s trace=%s",
            data.workflow_run_id, data.subject, data.channel, data.timeout_seconds, data.organization_id, self._trace_id
        )

        # activity headers carry trace_id forward
        act_headers = {}
        if self._trace_id:
            act_headers = {b"trace_id": self._trace_id.encode("utf-8")}

        self._handoff_id = await workflow.execute_activity(
            create_handoff,
            {
                "workflow_run_id": data.workflow_run_id,
                "subject": data.subject,
                "channel": data.channel,
                "payload": {**(data.payload or {}), "trace_id": self._trace_id},  # also in body
                "timeout_seconds": data.timeout_seconds,
                "created_by": data.created_by,
                "assignee": data.assignee,
                "organization_id": data.organization_id,
            },
            start_to_close_timeout=workflow.timedelta(seconds=20),
            # headers=act_headers,  # <-- carry trace
        )
        self._log.info("Created handoff_id=%s", self._handoff_id)

        timeout_td = timedelta(seconds=data.timeout_seconds)
        self._log.info("Waiting for resolve up to %s", timeout_td)

        resolved = await workflow.wait_condition(lambda: self._resolved, timeout=timeout_td)
        if not resolved and self._resolved:
            # defensive guard (kept from your working version)
            resolved = True

        if resolved:
            self._log.info("Resolved before timeout; applying resolution via RPC")
            await workflow.execute_activity(
                resolve_handoff_rpc,
                {
                    "handoff_id": self._handoff_id,
                    "resolution_payload": {**self._resolution_payload, "trace_id": self._trace_id},
                },
                start_to_close_timeout=workflow.timedelta(seconds=20),
                # headers=act_headers,
            )
            outcome = "resolved"
        else:
            self._log.info("Timed out after %s seconds; marking as timed_out", data.timeout_seconds)
            await workflow.execute_activity(
                mark_timed_out,
                {"handoff_id": self._handoff_id, "trace_id": self._trace_id},
                start_to_close_timeout=workflow.timedelta(seconds=20),
                # headers=act_headers,
            )
            outcome = "timed_out"

        return HandoffResult(
            handoff_id=self._handoff_id or "",
            outcome=outcome,
            resolution_payload=self._resolution_payload,
        )
