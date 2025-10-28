# scripts/respond_live.py
import asyncio
import json
import logging
from temporalio.client import Client

TEMPORAL_TARGET = "127.0.0.1:7233"
TEMPORAL_NAMESPACE = "default"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("respond_live")

async def main():
    client = await Client.connect(TEMPORAL_TARGET, namespace=TEMPORAL_NAMESPACE)

    # Load workflow ID from JSON
    try:
        with open("current_workflow.json") as f:
            wf_id = json.load(f).get("workflow_id")
        if not wf_id:
            raise FileNotFoundError
    except FileNotFoundError:
        log.error("❌ No active workflow found. Start a test first.")
        return

    log.info(f"📡 Connecting to running workflow {wf_id} ...")
    handle = client.get_workflow_handle(wf_id)
    log.info("💬 Type messages as 'voice: text' or 'sms: text' (type 'exit' to quit):")

    while True:
        line = input("> ").strip()
        if not line:
            continue
        if line.lower() == "exit":
            break

        if ":" not in line:
            log.warning("⚠️ Format: 'voice: message' or 'sms: message'")
            continue

        channel, message = [part.strip() for part in line.split(":", 1)]

        # ✅ FIXED: pass both parameters as args list
        await handle.signal("inbound_reply", args=[channel, message])
        log.info(f"📩 Sent signal to {wf_id}: {channel} → {message}")

if __name__ == "__main__":
    asyncio.run(main())
