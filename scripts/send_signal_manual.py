import asyncio
import sys
from temporalio.client import Client

async def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/send_signal_manual.py <workflow_id>")
        sys.exit(1)

    workflow_id = sys.argv[1]
    client = await Client.connect("127.0.0.1:7233", namespace="default")
    handle = client.get_workflow_handle(workflow_id)

    # Let user type message interactively
    message = input("📞 Enter your phone reply message: ")

    print(f"📩 Sending inbound_reply (voice) to workflow {workflow_id}...")
    # ✅ Pass signal arguments as a tuple
    await handle.signal("inbound_reply", ("voice", message))

    print("✅ Signal sent successfully.")

asyncio.run(main())
