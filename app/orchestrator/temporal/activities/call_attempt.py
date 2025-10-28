from temporalio import activity
import asyncio, random, logging

@activity.defn
async def call_attempt(phone_number: str, attempt_no: int) -> dict:
    logging.info(f"[CALL] Simulating call to {phone_number} (attempt {attempt_no})...")
    await asyncio.sleep(5)
    answered = random.choice([True, False])
    return {"status": "answered" if answered else "no_answer", "duration": 5}
