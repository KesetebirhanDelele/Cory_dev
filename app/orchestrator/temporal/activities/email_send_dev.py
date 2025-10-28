from temporalio import activity
import asyncio, logging

@activity.defn
async def email_send(recipient: str, subject: str, body: str) -> dict:
    logging.info(f"[EMAIL] Mock send to {recipient}: {subject}")
    await asyncio.sleep(1)
    return {"status": "sent", "provider": "mock"}
