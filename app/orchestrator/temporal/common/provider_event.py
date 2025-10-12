# 2) app/orchestrator/temporal/common/provider_event.py

from typing import Dict, Literal, Optional
from pydantic import BaseModel, Field, ValidationError

Status = Literal["delivered", "failed", "replied", "completed", "bounced", "queued"]
Channel = Literal["sms", "email", "voice"]

class ProviderEvent(BaseModel):
    """
    Canonical provider_event payload used as Temporal signal input and for A's bridge tests.
    """
    status: Status = Field(..., description="Terminal or notable provider state")
    provider_ref: str = Field(..., description="Provider-side id (message/call id)")
    channel: Channel = Field(..., description="sms | email | voice")
    activity_id: str = Field(..., description="Our activity id or external reference")
    data: Dict = Field(default_factory=dict, description="Optional provider/raw details")

    # --- Helpers -------------------------------------------------------------

    @classmethod
    def from_dict(cls, payload: Dict) -> "ProviderEvent":
        """Validate and coerce an incoming dict to a ProviderEvent."""
        return cls(**payload)

    def to_signal_dict(self) -> Dict:
        """Return the minimal dict Cory’s workflow expects on the signal wire."""
        return {
            "status": self.status,
            "provider_ref": self.provider_ref,
            "channel": self.channel,
            "activity_id": self.activity_id,
            "data": self.data or {},
        }

def validate_provider_event(payload: Dict) -> tuple[bool, Optional[str]]:
    """
    Lightweight validator for bridge code: returns (ok, error_message).
    """
    try:
        ProviderEvent.from_dict(payload)
        return True, None
    except ValidationError as ve:
        return False, ve.errors().__repr__()
