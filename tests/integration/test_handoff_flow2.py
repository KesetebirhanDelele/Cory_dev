# tests/integration/test_handoff_flow.py
import os
import uuid
import pytest
from temporalio.client import Client
from app.orchestrator.temporal.workflows.handoff import HandoffWorkflow, HandoffInput

pytestmark = pytest.mark.timeout(40)  # ok to remove if you don't have pytest-timeout

@pytest.mark.asyncio
async def test_handoff_resolves_before_timeout():
    client = await Client.connect(
        os.getenv("TEMPORAL_TARGET", "127.0.0.1:7233"),
        namespace=os.getenv("TEMPORAL_NAMESPACE", "default"),
    )
    run_id = str(uuid.uuid4())
    wf_id = f"test-handoff-{run_id}"
    handle = await client.start_workflow(
        HandoffWorkflow.run,
        HandoffInput(
            workflow_run_id=run_id,
            subject="Manual review needed",
            channel="slack",
            payload={"applicant_id": "A-123"},
            timeout_seconds=20,
            organization_id=os.environ.get("TEST_ORG_ID"),  # must be set in env
        ),
        id=wf_id,
        task_queue=os.getenv("TEMPORAL_TASK_QUEUE", "cory-campaigns"),
    )
    await handle.signal(HandoffWorkflow.resolve, {"decision": "approved", "by": "agent_42"})
    result = await handle.result()
    assert result.outcome == "resolved"
