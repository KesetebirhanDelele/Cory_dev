from temporalio import activity
import asyncio
import time

# Global state for simulated calls
ACTIVE_CALLS = {}

@activity.defn(name="voice_start")
async def voice_start(payload: dict) -> dict:
    """
    Mock call activity.
    Rings up to 10 seconds unless interrupted by ACTIVE_CALLS[to] = "answered".
    """
    to = payload.get("to")
    attempt = payload.get("attempt", 1)
    campaign = payload.get("campaign_id", "mock")
    duration = 10  # seconds

    activity.logger.info(f"📞 [MOCK CALL] Calling {to} (attempt {attempt}) in campaign {campaign}")
    ACTIVE_CALLS[to] = "ringing"
    start = time.time()

    for _ in range(duration):
        await asyncio.sleep(1)
        if ACTIVE_CALLS.get(to) == "answered":
            activity.logger.info(f"☎️ {to} answered early — ending call.")
            break

    status = "answered" if ACTIVE_CALLS.get(to) == "answered" else "no_answer"
    ACTIVE_CALLS.pop(to, None)
    provider_ref = f"mock-call-{int(time.time())}"

    activity.logger.info(f"📞 [MOCK RESULT] {to} -> {status} | ref={provider_ref}")
    return {
        "channel": "voice",
        "status": status,
        "provider_ref": provider_ref,
        "duration": round(time.time() - start, 1),
        "mock": True,
        "payload": payload,
    }
