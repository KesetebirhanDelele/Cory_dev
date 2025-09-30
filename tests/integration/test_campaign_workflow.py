# tests/integration/test_campaign_workflow.py
import asyncio
import os
import pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.orchestrator.temporal.workflows.campaign import CampaignWorkflow
from app.orchestrator.temporal.activities.sms_send import sms_send
from app.orchestrator.temporal.activities.email_send import email_send
from app.orchestrator.temporal.activities.voice_start import voice_start

pytestmark = pytest.mark.asyncio


async def test_signal_completes():
    # Helpful logs while debugging locally
    os.environ.setdefault("TEMPORAL_PY_SDK_LOG_LEVEL", "INFO")

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = env.client

        async with Worker(
            client,
            task_queue="cory-campaigns",
            workflows=[CampaignWorkflow],
            activities=[sms_send, email_send, voice_start],
        ):
            # Give worker a tick to fully start
            await asyncio.sleep(0.05)

            handle = await client.start_workflow(
                CampaignWorkflow.run,
                id="wf-campaign-1",
                task_queue="cory-campaigns",
                args=[
                    "enr_42",
                    {
                        "action": "send_sms",
                        "payload": {"msg": "hi"},
                        "await_timeout_seconds": 60,
                    },
                ],
            )

            # SEND SIGNAL *IMMEDIATELY* (it will buffer until the workflow awaits it)
            await handle.signal(
                "provider_event",
                {
                    "status": "delivered",
                    "provider_ref": "stub-sms-enr_42",
                    "data": {"code": "200"},
                },
            )

            # Nudge the env so the run reaches wait_condition and consumes the buffered signal
            await env.sleep(0.3)  # bump to 0.5 on slow Windows if needed

            # Hard cap so test never hangs
            result = await asyncio.wait_for(handle.result(), timeout=10)

            # Assertions
            assert result["attempt"]["channel"] == "sms"
            assert result["final"]["status"] == "delivered"
            assert result["final"]["provider_ref"] == "stub-sms-enr_42"
