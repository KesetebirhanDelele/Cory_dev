# app/orchestrator/temporal/workflows/workflow_registry.py
from __future__ import annotations

from typing import Optional, Any, Type
from temporalio.client import WorkflowHandle, Client
from temporalio import workflow

_latest_handle: Optional[WorkflowHandle] = None
_client: Optional[Client] = None


# ===============================================================
#  Handle Management
# ===============================================================

def set_current_handle(handle: WorkflowHandle):
    """Store the most recent workflow handle for later inspection."""
    global _latest_handle
    _latest_handle = handle


def get_current_handle() -> Optional[WorkflowHandle]:
    """Return the most recently started workflow handle."""
    return _latest_handle


def clear_current_handle():
    """Reset stored handle (mostly used in tests)."""
    global _latest_handle
    _latest_handle = None


# ===============================================================
#  Client Management
# ===============================================================

def set_client(client: Client):
    """Set the Temporal client once, typically at worker startup."""
    global _client
    _client = client


def get_client() -> Client:
    """Return the globally configured Temporal client."""
    if _client is None:
        raise RuntimeError("Temporal client not yet initialized in workflow_registry.")
    return _client


# ===============================================================
#  Workflow Launcher Helpers
# ===============================================================

async def start_workflow(
    workflow_type: Type[Any],
    input_obj: Any,
    *,
    workflow_id: Optional[str] = None,
    task_queue: Optional[str] = None,
) -> WorkflowHandle:
    """
    Unified helper to start any workflow and automatically register its handle.
    Used by Tickets 5, 7, 8, 9.

    Args:
        workflow_type: The workflow class reference (not string).
        input_obj: The dataclass input to pass to workflow.run().
        workflow_id: Optional explicit workflow ID.
        task_queue: Optional task queue override.
    """
    client = get_client()

    handle = await client.start_workflow(
        workflow_type,
        input_obj,
        id=workflow_id,
        task_queue=task_queue or "cory-default",
    )

    set_current_handle(handle)
    return handle


# ===============================================================
#  Query Helpers (Optional Safety Utilities)
# ===============================================================

async def get_workflow_result(handle: Optional[WorkflowHandle] = None):
    """
    Return the result of a workflow. If handle omitted, uses the latest handle.
    """
    h = handle or get_current_handle()
    if h is None:
        raise RuntimeError("No workflow handle available for get_workflow_result().")
    return await h.result()


async def get_workflow_status(handle: Optional[WorkflowHandle] = None):
    """
    Query a workflow's status (running, completed, failed, etc.)
    """
    h = handle or get_current_handle()
    if h is None:
        raise RuntimeError("No workflow handle available for get_workflow_status().")
    desc = await h.describe()
    return desc.status.name
