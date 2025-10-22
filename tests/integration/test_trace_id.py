import os, uuid, pytest
from temporalio.client import Client
from app.orchestrator.temporal.workflows.handoff import HandoffWorkflow, HandoffInput

ORG_ID = os.getenv("TEST_ORG_ID")

@pytest.mark.asyncio
async def test_trace_id_roundtrip():
    target = os.getenv("TEMPORAL_TARGET", "127.0.0.1:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    queue = os.getenv("TEMPORAL_TASK_QUEUE", "cory-campaigns")

    client = await Client.connect(target, namespace=namespace)

    trace_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    wf_id = f"test-trace-{run_id}"

    handle = await client.start_workflow(
    HandoffWorkflow.run,
    HandoffInput(
        workflow_run_id=run_id,
        subject="trace-test",
        channel="slack",
        payload={"applicant_id": "T-1", "trace_id": trace_id},
        timeout_seconds=30,
        organization_id=ORG_ID,   # ensure a UUID gets sent
    ),
    id=wf_id,
    task_queue=queue,
    )

    await handle.signal("resolve", {"decision": "approved", "by": "tester", "trace_id": trace_id})
    result = await handle.result()
    assert result.outcome == "resolved"
