"""
End-to-end test for MissedCallFollowupWorkflow.

Flow:
- start MissedCallFollowupWorkflow
- send provider_event=no_answer (1st missed call)
- wait a bit (to let workflow schedule SMS / retry)
- send provider_event=no_answer again (retry missed)
- print final result

Requires:
- temporal dev server running on localhost:7233
- python -m app.orchestrator.temporal.worker running
"""

import asyncio
from datetime import timedelta

from temporalio.client import Client

from app.orchestrator.temporal.workflows.missed_call_followup import (
    MissedCallFollowupWorkflow,
)

# --------------------------------------------------------------------
# Test constants – update phone numbers if you want
# --------------------------------------------------------------------
FROM_NUMBER = "+15714782790"   # student
TO_NUMBER = "+16822812224"     # your Cory/Twilio number
WORKFLOW_ID = "dev-missed-call-test-1"
TASK_QUEUE = "cory-handoff-queue"   # same as TEMPORAL_COMM_TASK_QUEUE


async def run_test() -> None:
    print("🔌 Connecting to Temporal at localhost:7233 ...")
    client = await Client.connect("localhost:7233")

    # ----------------------------------------------------------------
    # 1) Start the MissedCallFollowupWorkflow
    #    NOTE: only TWO positional args to start_workflow:
    #          (workflow, ...) and pass run args via args=[...]
    # ----------------------------------------------------------------
    print("🚀 Starting MissedCallFollowupWorkflow…")
    handle = await client.start_workflow(
        MissedCallFollowupWorkflow.run,
        id=WORKFLOW_ID,
        task_queue=TASK_QUEUE,
        args=[FROM_NUMBER, TO_NUMBER, "no_answer"],
        run_timeout=timedelta(minutes=5),
    )

    print(f"✅ Started workflow: id={handle.id}, run_id={handle.run_id}")

    # ----------------------------------------------------------------
    # 2) Simulate first missed call
    # ----------------------------------------------------------------
    print("📡 Sending provider_event: no_answer (1st attempt)")
    await handle.signal(
        "provider_event",
        {"status": "no_answer", "data": {"intent": "no_answer"}},
    )

    print("⏳ Waiting ~20s for internal timers / SMS #1 …")
    await asyncio.sleep(20)

    # ----------------------------------------------------------------
    # 3) Simulate second missed call (retry)
    # ----------------------------------------------------------------
    print("📡 Sending provider_event: no_answer (2nd attempt)")
    await handle.signal(
        "provider_event",
        {"status": "no_answer", "data": {"intent": "no_answer"}},
    )

    print("⏳ Waiting a few seconds for SMS #2 / completion …")
    await asyncio.sleep(10)

    # ----------------------------------------------------------------
    # 4) Wait for result and print
    # ----------------------------------------------------------------
    result = await handle.result()
    print("\n==================== FINAL WORKFLOW RESULT ====================")
    print(result)
    print("===============================================================\n")
    print("🎉 Missed-call test completed")


if __name__ == "__main__":
    asyncio.run(run_test())
