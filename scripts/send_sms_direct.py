# scripts/send_sms_direct.py
import asyncio
import logging
import os

from dotenv import load_dotenv

# This is the same client sms_send() uses internally
from app.channels.providers import sms as sms_client


log = logging.getLogger("cory.scripts.send_sms_direct")


async def main() -> None:
    load_dotenv()  # load your .env so Twilio creds / provider config are available

    # Hard-code or read from env
    to = os.getenv("TEST_SMS_TO", "+15714782790")
    body = "Test from send_sms_direct.py 🚀"

    log.info("Sending direct SMS | to=%s | body=%s", to, body)

    ref = await sms_client.send(
        to=to,
        body=body,
        idempotency_key="direct-test-1",
    )

    log.info("✅ Provider returned ref=%s", ref)
    print("provider_ref:", ref)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
