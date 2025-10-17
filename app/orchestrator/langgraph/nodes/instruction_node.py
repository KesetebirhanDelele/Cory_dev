from __future__ import annotations
from typing import Dict
from app.orchestrator.temporal.common.instruction import Instruction

def make_instruction(job: Dict) -> Instruction:
    """
    Maps a v_due_actions row (or similar job dict) to a deterministic Instruction.
    """
    ch = (job.get("next_channel") or job.get("channel") or "").strip().lower()
    enrollment_id = job.get("enrollment_id")

    if ch == "sms":
        return Instruction(
            action="SendSMS",
            payload={
                "enrollment_id": enrollment_id,
                "step_id": job.get("current_step_id"),
                "campaign_id": job.get("campaign_id"),
            },
        )

    if ch == "email":
        return Instruction(
            action="SendEmail",
            payload={
                "enrollment_id": enrollment_id,
                "template": "intro",
                "step_id": job.get("current_step_id"),
                "campaign_id": job.get("campaign_id"),
            },
        )

    if ch == "voice":
        return Instruction(
            action="StartCall",
            payload={
                "enrollment_id": enrollment_id,
                "agent_id": "followup_agent",
                "step_id": job.get("current_step_id"),
                "campaign_id": job.get("campaign_id"),
            },
        )

    return Instruction(action="noop", payload={"enrollment_id": enrollment_id})
