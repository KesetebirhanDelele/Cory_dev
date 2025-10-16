# tests/integration/test_handoff_temporal.py
# tests/integration/test_handoff_flow.py
import os, uuid, pytest
from temporalio.client import Client
from app.orchestrator.temporal.workflows.handoff import HandoffWorkflow, HandoffInput

TEST_ORG_ID = os.environ["TEST_ORG_ID"]  # set this in the test terminal

@pytest.mark.asyncio
async def test_handoff_resolves_before_timeout():
    client = await Client.connect(os.getenv("TEMPORAL_TARGET","127.0.0.1:7233"),
                                  namespace=os.getenv("TEMPORAL_NAMESPACE","default"))
    run_id = str(uuid.uuid4())
    handle = await client.start_workflow(
        HandoffWorkflow.run,
        HandoffInput(
            workflow_run_id=run_id,
            subject="Manual review needed",
            channel="slack",
            payload={"applicant_id": "A-123"},
            timeout_seconds=20,
            organization_id=TEST_ORG_ID,     # <-- here
        ),
        id=f"test-handoff-{run_id}",
        task_queue=os.getenv("TEMPORAL_TASK_QUEUE","cory-campaigns"),
    )
    try:
        await handle.signal(HandoffWorkflow.resolve, {"decision": "approved", "by": "agent_42"})
        result = await handle.result()  # returns HandoffResult dataclass
        assert result.outcome == "resolved"
    finally:
        # If test failed before completion, make sure we don't leave an open run
        try:
            await handle.cancel()
        except Exception:
            pass

@pytest.mark.asyncio
async def test_handoff_resolves_before_timeout():
    client = await Client.connect(TEMPORAL_TARGET, namespace=TEMPORAL_NAMESPACE)
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
        ),
        id=wf_id,
        task_queue=TASK_QUEUE,  # <— uses env
    )
    await handle.signal(HandoffWorkflow.resolve, {"decision": "approved", "by": "agent_42"})
    result = await handle.result()
    assert result.outcome == "resolved"
