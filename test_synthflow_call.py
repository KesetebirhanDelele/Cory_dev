from dotenv import load_dotenv
load_dotenv()  # load variables from .env

import asyncio
from app.channels.providers.Voice.synthflow_adapter import send_voice_call

async def main():
    phone = "+12063318153"  # your real number
    print(f"🚀 Making call to: {phone}")
    result = await send_voice_call("org1", "test-enrollment", phone)
    print("Response:", result)

if __name__ == "__main__":
    asyncio.run(main())
