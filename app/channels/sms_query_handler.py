# app/channels/sms_query_handler.py
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

from app.orchestrator.temporal.workflows.answer_builder import AnswerWorkflow

logger = logging.getLogger(__name__)


async def handle_inbound_sms(
    *,
    client: Client,
    from_number: str,
    body: str,
    provider_ref: Optional[str] = None,
    threshold: float = 0.5,
) -> Dict[str, Any]:
    """
    Entry point used by the SMS webhook to hand an inbound message to Temporal.

    - If the AnswerWorkflow for this phone number is not running yet, start it.
    - If it is already running, just send a signal with the new SMS payload.

    Returns a small dict with workflow metadata.
    """

    # Stable workflow ID per phone number (strip "+" so it's ID-safe)
    safe_number = from_number.replace("+", "")
    workflow_id = f"answer-builder-{safe_number}"

    inbound_id = provider_ref or f"sms-{uuid.uuid4()}"
    payload: Dict[str, Any] = {
        "from": from_number,
        "body": body,
        "provider_ref": provider_ref,
        "inbound_id": inbound_id,
    }

    logger.info(
        "📨 [SMS_QUERY_HANDLER] inbound | from=%s | body=%s | workflow_id=%s",
        from_number,
        body,
        workflow_id,
    )

    # 1) Try to start the workflow the first time we see this number
    try:
        handle = await client.start_workflow(
            AnswerWorkflow.run,
            # 👇 IMPORTANT: multiple workflow args must go via `args=[...]`
            args=[body, from_number, inbound_id, threshold],
            id=workflow_id,
            task_queue="rag-q",
        )
        logger.info(
            "🧠 Started AnswerWorkflow for %s | run_id=%s",
            from_number,
            handle.run_id,
        )
        started = True

    except WorkflowAlreadyStartedError:
        # 2) If it already exists, just signal it with the new SMS payload
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal(AnswerWorkflow.sms_inbound_signal, payload)
        logger.info(
            "📡 Signaled existing AnswerWorkflow for %s | workflow_id=%s",
            from_number,
            workflow_id,
        )
        started = False

    return {
        "workflow_id": workflow_id,
        "run_id": getattr(handle, "run_id", None),
        "started": started,
        "inbound_id": inbound_id,
    }
