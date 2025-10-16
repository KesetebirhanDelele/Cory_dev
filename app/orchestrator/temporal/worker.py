import asyncio, os, sys, logging, signal
from temporalio.client import Client
from temporalio.worker import Worker

from app.orchestrator.temporal.workflows.campaign import CampaignWorkflow
from app.orchestrator.temporal.activities.sms_send import sms_send
from app.orchestrator.temporal.activities.email_send import email_send
from app.orchestrator.temporal.activities.voice_start import voice_start
from app.orchestrator.temporal.workflows.handoff import HandoffWorkflow
from app.orchestrator.temporal.activities.handoff_create import (
    create_handoff, resolve_handoff_rpc, mark_timed_out,
)

TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "cory-campaigns")
TEMPORAL_TARGET = os.getenv("TEMPORAL_TARGET", "127.0.0.1:7233")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")

log = logging.getLogger(__name__)

async def run():
    client = await Client.connect(TEMPORAL_TARGET, namespace=TEMPORAL_NAMESPACE)
    log.info("Connected to Temporal at %s (ns=%s)", TEMPORAL_TARGET, TEMPORAL_NAMESPACE)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    # Only register OS signal handlers on POSIX; Windows raises NotImplementedError
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)

    try:
        async with Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[CampaignWorkflow, HandoffWorkflow],
            activities=[sms_send, email_send, voice_start, create_handoff, resolve_handoff_rpc, mark_timed_out],
        ):
            log.info("Worker started on task queue: %s", TASK_QUEUE)
            if sys.platform == "win32":
                # On Windows, just wait forever; Ctrl+C raises KeyboardInterrupt
                await asyncio.Future()
            else:
                await stop_event.wait()
    except KeyboardInterrupt:
        log.info("KeyboardInterrupt — shutting down worker")

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run())

if __name__ == "__main__":
    main()
