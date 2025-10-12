# app/orchestrator/temporal/common/attempts.py
from typing import Dict, Literal, Optional
from pydantic import BaseModel, Field


ProviderEventKind = Literal["delivered", "failed", "timeout", "policy_denied"]

class Attempt(BaseModel):
    """
    Pure, deterministic description of what we intend to attempt.
    No provider IDs or side effects here.
    """
    action: str
    params: Dict = Field(default_factory=dict)

class AwaitSpec(BaseModel):
    """
    What the workflow will wait on after issuing the Attempt.
    This expresses ONLY the expectation; no I/O or provider coupling.
    """
    expect: ProviderEventKind  # e.g., "delivered" (happy path)
    timeout_seconds: int = 30
    on_timeout: ProviderEventKind = "timeout"
