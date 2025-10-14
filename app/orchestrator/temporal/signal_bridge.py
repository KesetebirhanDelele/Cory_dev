# app/orchestrator/temporal/signal_bridge.py
import logging
import asyncio

logger = logging.getLogger("cory.signal_bridge")


async def send_temporal_signal(workflow_id: str, event_dict: dict) -> bool:
    """
    Mock Temporal signal bridge.
    In real system: send provider_event(event_dict) signal to Temporal workflow.
    """
    await asyncio.sleep(0)  # Simulate async I/O
    logger.info("Signal sent to workflow", extra={"workflow_id": workflow_id})
    return True

