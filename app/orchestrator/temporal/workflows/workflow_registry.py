# app/orchestrator/temporal/workflows/workflow_registry.py
from __future__ import annotations

from typing import Optional, Sequence, Type

from temporalio.client import WorkflowHandle

from app.orchestrator.temporal.workflows.book_appointment_workflow import (
    BookAppointmentWorkflow,
)

_latest_handle: Optional[WorkflowHandle] = None


def set_current_handle(handle: WorkflowHandle) -> None:
    """Store the most recently started workflow handle (used in tests/tools)."""
    global _latest_handle
    _latest_handle = handle


def get_current_handle() -> Optional[WorkflowHandle]:
    """Return the most recently stored workflow handle, if any."""
    return _latest_handle


def get_registered_workflows() -> Sequence[Type]:
    """
    Return the list of workflows this worker should register.

    Right now this only includes the BookAppointmentWorkflow added for Ticket 5,
    but more workflows can be appended here over time.
    """
    return [BookAppointmentWorkflow]
