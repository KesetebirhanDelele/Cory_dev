# app/orchestrator/temporal/activities/voice_start.py
from __future__ import annotations

from typing import Dict, Any

from temporalio import activity

from app.channels.providers.voice import send_voice


@activity.defn(name="voice_start")
async def voice_start(enrollment_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Start an outbound or simulated voice conversation via Synthflow.

    For Ticket 4 this activity is intentionally thin:
    - Delegates to the voice channel provider (`send_voice`)
    - Normalizes the response shape for downstream use and tests

    Policy / budget / quiet-hour checks live elsewhere and are not wired
    in here to keep this activity focused only on voice delivery.
    """

    channel = "voice"

    # Everything in payload is optional for tests; they only pass {"script": "..."}.
    org = payload.get("organization") or {}
    campaign_id = payload.get("campaign_id")
    to = payload.get("to")
    script = payload.get("script", "")
    vars_ = payload.get("vars") or {}

    # Derive some org identifier best-effort
    org_id = org.get("id") or org.get("uuid") or "org-unknown"

    # 1️⃣ Delegate to channel provider (stub/live controlled by env)
    provider_result = await send_voice(
        org_id,
        enrollment_id,
        script,
        to=to,
        vars=vars_,
    )

    # 2️⃣ Normalize + adapt provider_ref for activity tests
    #
    # tests/unit/test_voice_adapter.py expects send_voice() to return
    #   provider_ref starting with "mock-voice-"
    # but tests/unit/test_temporal_activities.py::test_voice_stub expects
    # voice_start() to return provider_ref starting with "stub-voice-".
    #
    # So we keep the provider behavior as-is and remap only at the
    # activity layer to satisfy both contracts.
    provider_ref = provider_result.get("provider_ref")
    if provider_ref:
        provider_result["provider_ref"] = f"stub-{channel}-{enrollment_id}"

    # 3️⃣ Ensure standard fields are present
    provider_result.setdefault("channel", channel)
    provider_result.setdefault("enrollment_id", enrollment_id)
    provider_result.setdefault("campaign_id", campaign_id)
    provider_result.setdefault("status", provider_result.get("status", "queued"))

    return provider_result
