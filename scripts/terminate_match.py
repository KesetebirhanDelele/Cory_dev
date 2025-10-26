import asyncio, os, sys
from temporalio.client import Client

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True), override=False)

async def main(wfid):
    client = await Client.connect(os.getenv("TEMPORAL_TARGET","127.0.0.1:7233"),
                                  namespace=os.getenv("TEMPORAL_NAMESPACE","default"))
    h = client.get_workflow_handle(workflow_id=wfid)
    try:
        await h.terminate("reset after code fix")
        print("terminated:", wfid)
    except Exception as e:
        print("no existing workflow to terminate:", e)

if __name__ == "__main__":
    wfid = sys.argv[1] if len(sys.argv) > 1 else "match-00000000-0000-0000-0000-000000000001"
    asyncio.run(main(wfid))
