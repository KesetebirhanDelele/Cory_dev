# tests/sms/send_test_sms.py
import asyncio
import os
from dotenv import load_dotenv

# Load the environment variables from .env
load_dotenv()

# Import the SMS provider
from app.channels.providers.sms import send_sms_via_slicktext


async def run_test_sms():
    """
    Sends a single real SMS using SlickText through Cory's provider.
    """

    print("\n---- Cory SMS Test ----")

    # Read environment variables
    live_channels = os.getenv("CORY_LIVE_CHANNELS")
    fake_mode = os.getenv("HANDOFF_FAKE_MODE")
    api_key = os.getenv("SLICKTEXT_API_KEY")

    # Safety checks
    if live_channels != "1":
        print("❌ CORY_LIVE_CHANNELS is NOT set to 1.")
        print("   Cory is in STUB MODE. No real SMS will be sent.\n")
        return

    if fake_mode and fake_mode.lower() in {"1", "true"}:
        print("❌ HANDOFF_FAKE_MODE is enabled.")
        print("   Cory is in STUB MODE. No real SMS will be sent.\n")
        return

    if not api_key:
        print("❌ Missing SLICKTEXT_API_KEY in environment.")
        return

    to_number = input("Enter the phone number to test (E.164 format, e.g. +15551234567): ").strip()

    if not to_number.startswith("+"):
        print("❌ Phone number must be in E.164 format starting with +")
        return

    print(f"\n📨 Sending SMS to: {to_number}\n")

    result = await send_sms_via_slicktext(
        to=to_number,
        body="🚀 Hello from Cory! This is a live test SMS sent using SlickText.",
        org_id="sms-test-org",
        enrollment_id="sms-test-enrollment"
    )

    print("---- Provider Result ----")
    print(result)
    print("\n✅ Done. If everything is correct, your phone should receive a message.\n")


if __name__ == "__main__":
    asyncio.run(run_test_sms())
