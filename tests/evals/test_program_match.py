import os
import pytest
from temporalio.client import Client

@pytest.mark.asyncio
async def test_program_match_determinism_and_api():
    target = os.getenv("TEMPORAL_TARGET", "localhost:7233")
    queue = os.getenv("AI_MATCH_QUEUE", "ai-match-q")
    client = await Client.connect(target)

    lead_id = os.getenv("TEST_LEAD_ID", "00000000-0000-0000-0000-000000000001")
    h = await client.start_workflow("ProgramMatchWf", lead_id, id=f"match-{lead_id}", task_queue=queue)
    res1 = await h.result()

    await h.signal("LeadUpdated", lead_id)
    h2 = client.get_workflow_handle(workflow_id=f"match-{lead_id}")
    res2 = await h2.result()

    assert res1.fingerprint == res2.fingerprint
    assert sorted([(s.program_id, s.score) for s in res1.scores]) == \
           sorted([(s.program_id, s.score) for s in res2.scores])
