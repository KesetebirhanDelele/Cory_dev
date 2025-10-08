# app/web/schemas.py
from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, Optional, Literal
from uuid import UUID
from pydantic import BaseModel, Field, ValidationError, model_validator


# --------------------------------------------------------------------
# Base canonical event model
# --------------------------------------------------------------------
class WebhookEvent(BaseModel):
    """Canonical webhook event model used to normalize incoming signals."""

    event: str = Field(..., description="Canonical event name, e.g. 'lead_created'")
    channel: str = Field(..., description="Channel: 'email'|'sms'|'voice'|'webhook'")
    timestamp: datetime = Field(..., description="ISO8601 UTC timestamp")
    payload: Dict[str, Any] = Field(default_factory=dict)
    lead_id: Optional[UUID] = None
    campaign_id: Optional[UUID] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}  # reject unexpected top-level keys

    @model_validator(mode="before")
    def normalize_inputs(cls, v: dict) -> dict:
        """Normalize input variations (e.g. time→timestamp, infer channel)."""
        if not isinstance(v, dict):
            return v

        # canonicalize event name
        if "event" in v and isinstance(v["event"], str):
            v["event"] = v["event"].strip().lower()

        # alias time→timestamp
        if "time" in v and "timestamp" not in v:
            v["timestamp"] = v.pop("time")

        # infer channel if missing
        if "channel" not in v:
            p = v.get("payload", {})
            if isinstance(p, dict):
                if "email" in p or "subject" in p:
                    v["channel"] = "email"
                elif "phone" in p or "message" in p:
                    v["channel"] = "sms"
                elif "call_id" in p or "transcript" in p:
                    v["channel"] = "voice"
                else:
                    v["channel"] = "webhook"
        return v


# --------------------------------------------------------------------
# Per-channel variants (strongly typed using Literal)
# --------------------------------------------------------------------
class EmailWebhookEvent(WebhookEvent):
    channel: Literal["email"] = "email"
    payload: Dict[str, Any] = Field(
        ..., description="Must include 'to' and 'subject' for email"
    )


class SmsWebhookEvent(WebhookEvent):
    channel: Literal["sms"] = "sms"
    payload: Dict[str, Any] = Field(
        ..., description="Must include 'phone' and 'message' for sms"
    )


class VoiceWebhookEvent(WebhookEvent):
    channel: Literal["voice"] = "voice"
    payload: Dict[str, Any] = Field(
        ..., description="Should include 'call_id' and optional 'transcript'"
    )


# --------------------------------------------------------------------
# Normalization factory helper
# --------------------------------------------------------------------
def normalize_webhook_event(raw: dict) -> WebhookEvent:
    """
    Try channel-specific validation first, fallback to base WebhookEvent.
    Raises ValidationError if invalid.
    """
    if not isinstance(raw, dict):
        raise ValidationError("Invalid payload type")

    channel = (raw.get("channel") or "").lower()

    try:
        if channel == "email":
            return EmailWebhookEvent.model_validate(raw)
        if channel == "sms":
            return SmsWebhookEvent.model_validate(raw)
        if channel == "voice":
            return VoiceWebhookEvent.model_validate(raw)
        # fallback
        return WebhookEvent.model_validate(raw)
    except ValidationError as e:
        raise e

