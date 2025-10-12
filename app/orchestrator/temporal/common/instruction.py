# app/orchestrator/temporal/common/instruction.py
from typing import Dict, Optional
from pydantic import BaseModel, Field


class Instruction(BaseModel):
    """
    Deterministic instruction for a single campaign step.
    No side-effects, pure data used by the workflow planner.
    """
    action: str = Field(..., description="semantic verb, e.g. 'SendSMS'|'SendEmail'|'StartCall'")
    payload: Dict = Field(default_factory=dict, description="parameters for the action (channel-agnostic)")
    await_timeout_seconds: Optional[int] = Field(
        30, ge=1, le=3600, description="how long to wait for provider_event before timing out"
    )
