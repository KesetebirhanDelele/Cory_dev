# scripts/test_outreach_signal_interrupt.py
import asyncio
import json
import logging
from datetime import datetime
from temporalio.client import Client
from temporalio.worker import Worker
from app.orchestrator.temporal.workflows.admissions_outreach import AdmissionsOutreachWorkflow
from app.orchestrator.temporal.activities.sms_send_dev import sms_send
from app.orchestrator.temporal.activities.email_send_dev import email_send
from app.orchestrator.temporal.activities.voice_start_dev import voice_start
from app.orchestrator.temporal.activities.escalate_to_human import escalate_to_human

TEMPORAL_TARGET = "127.0.0.1:7233"
TEMPORAL_NAMESPACE = "default"
TASK_QUEUE = "rag-q"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
log = logging.getLogger("signal-test")

async def run_workflow_with_signal():
    client = await Client.connect(TEMPORAL_TARGET, namespace=TEMPORAL_NAMESPACE)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[AdmissionsOutreachWorkflow],
        activities=[sms_send, email_send, voice_start, escalate_to_human],
    )

    lead = {
        "id": "lead-voice-signal",
        "name": "Signal Test Student",
        "phone": "+15555550222",
        "email": "signal.student@example.com",
    }

    async with worker:
        wf_id = f"test-outreach-signal-{datetime.now().timestamp()}"
        handle = await client.start_workflow(
            AdmissionsOutreachWorkflow.run,
            lead,
            id=wf_id,
            task_queue=TASK_QUEUE,
        )

        with open("current_workflow.json", "w") as f:
            json.dump({"workflow_id": wf_id}, f)

        log.info(f"🧠 Workflow started with ID: {wf_id}")
        log.info("💾 Saved workflow ID to current_workflow.json")
        log.info("💡 You can now open another terminal and run:")
        log.info("    python -m scripts.respond_live")
        log.info("💬 to send voice or SMS replies interactively.")
        log.info("Or type 'call' here anytime to simulate student answering directly.\n")

        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, input, "")
            if line.strip().lower() == "call":
                log.info("📞 Sending signal: voice → Student answered call.")
                await handle.signal("inbound_reply", "voice", "Student answered call")
                break

        result = await handle.result()
        log.info(f"✅ Workflow finished with result: {result}")

if __name__ == "__main__":
    asyncio.run(run_workflow_with_signal())
