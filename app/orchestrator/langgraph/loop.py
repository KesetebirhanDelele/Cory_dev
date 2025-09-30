# orchestrator_loop.py
import asyncio, os
from datetime import datetime, timezone
from dotenv import load_dotenv; load_dotenv()
from app.data.supabase_repo import sb
from app.channels import sms_sender

SCHEMA = os.getenv("SUPABASE_SCHEMA", "dev_nexus")
db = sb.postgrest.schema(SCHEMA)

async def tick():
    # 1) SMS: run the sender once (it reads v_due_sms_followups)
    sms_sender.run_sms_sender()

    # 2) Voice: pick active enrollments that are due for voice now
    due = db.from_("v_due_actions").select(
        "enrollment_id,next_channel,next_run_at"
    ).eq("next_channel","voice").execute().data

    for row in due:
        # For DEV: simulate provider result immediately (success or fail)
        from app.data.supabase_repo import now_iso
        from uuid import uuid4
        # Example: alternate fail/succeed
        status = "failed" if hash(row["enrollment_id"]) % 2 == 0 else "completed"
        db.rpc("usp_logvoicecallandadvance", {
            "p_enrollment_id": row["enrollment_id"],
            "p_provider_call_id": f"DEV-{uuid4()}",
            "p_provider_module_id": "mock",
            "p_duration_seconds": 60,
            "p_end_call_reason": status,
            "p_executed_actions": None,
            "p_prompt_variables": None,
            "p_recording_url": None,
            "p_transcript": None,
            "p_call_started_at": now_iso(),
            "p_agent_name": "DevBot",
            "p_call_timezone": "UTC",
            "p_phone_to": "+15555550123",
            "p_phone_from": "+15555550000",
            "p_call_status": status,
            "p_campaign_type": "live",
            "p_outcome": status,
            "p_classification": "followup" if status=="failed" else "booked"
        }).execute()

async def main():
    while True:
        await tick()
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
