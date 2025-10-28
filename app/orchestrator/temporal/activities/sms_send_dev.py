from temporalio import activity
import asyncio, time, logging

@activity.defn
async def sms_send(phone_number: str, message: str) -> dict:
    logging.info(f"[SMS] Mock send to {phone_number}: {message}")
    await asyncio.sleep(1)
    return {"status": "sent", "message_id": f"mock-{int(time.time())}"}
