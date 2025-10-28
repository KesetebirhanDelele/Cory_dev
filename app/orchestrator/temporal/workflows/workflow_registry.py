# app/orchestrator/temporal/workflows/workflow_registry.py
from typing import Optional
from temporalio.client import WorkflowHandle

_latest_handle: Optional[WorkflowHandle] = None

def set_current_handle(handle: WorkflowHandle):
    global _latest_handle
    _latest_handle = handle

def get_current_handle() -> Optional[WorkflowHandle]:
    return _latest_handle
