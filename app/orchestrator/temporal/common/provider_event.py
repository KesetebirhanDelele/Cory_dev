# app/orchestrator/temporal/common/provider_event.py

from typing import Dict, Literal, Optional, Any
from pydantic import BaseModel, Field, ValidationError

Status = Literal["delivered", "failed", "replied", "completed", "bounced", "queued"]
Channel = Literal["sms", "email", "voice"]


class ProviderEvent(BaseModel):
    """
    Canonical provider_event payload used as Temporal signal input and for bridge tests.

    Notes:
    - `status` is the final / notable state from the provider (delivered, failed, replied, etc.).
    - `provider_ref` is the provider-side identifier (e.g., message ID, call ID).
    - `channel` is the communication channel ("sms", "email", "voice").
    - `activity_id` is our internal reference / Temporal activity identifier.
    - `data` is a flexible bag for provider/raw details AND higher-level fields such as:
        {
          "intent": "ready_to_enroll" | "interested_but_not_ready" | ...,
          "next_action": "book_appointment" | "schedule_followup_phone" | ...,
          "from": "+1555...",
          ...
        }
      CampaignWorkflow and other consumers can branch on these fields.
    """

    status: Status = Field(..., description="Terminal or notable provider state")
    provider_ref: str = Field(..., description="Provider-side id (message/call id)")
    channel: Channel = Field(..., description="sms | email | voice")
    activity_id: str = Field(..., description="Our activity id or external reference")
    data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional provider/raw details (may include intent, next_action, etc.)",
    )

    # --- Helpers -------------------------------------------------------------

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ProviderEvent":
        """Validate and coerce an incoming dict to a ProviderEvent."""
        return cls(**payload)

    def to_signal_dict(self) -> Dict[str, Any]:
        """
        Return the minimal dict Cory’s workflow expects on the signal wire.

        Note: intent / next_action / etc. should be nested under `data`:
        {
          "status": "...",
          "provider_ref": "...",
          "channel": "...",
          "activity_id": "...",
          "data": {
              "intent": "...",
              "next_action": "...",
              ...
          }
        }
        """
        return {
            "status": self.status,
            "provider_ref": self.provider_ref,
            "channel": self.channel,
            "activity_id": self.activity_id,
            "data": self.data or {},
        }


def validate_provider_event(payload: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """
    Lightweight validator for bridge code: returns (ok, error_message).
    """
    try:
        ProviderEvent.from_dict(payload)
        return True, None
    except ValidationError as ve:
        return False, repr(ve.errors())
