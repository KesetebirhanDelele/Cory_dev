#from pydantic import BaseModel, Field
#from typing import Any, Dict

#class ProviderEvent(BaseModel):
    #status: str = Field(..., examples=["delivered", "failed", "replied"])
    #provider_ref: str = Field(..., examples=["abc123"])
    #data: Dict[str, Any] = Field(default_factory=dict)  # raw provider payload
from pydantic import BaseModel, Field
from typing import Literal, Optional, Dict, Any
from datetime import datetime
import uuid

class WebhookEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str
    channel: Literal["sms", "email", "voice"]
    payload: Dict[str, Any]
    received_at: datetime = Field(default_factory=datetime.utcnow)
    idempotency_key: Optional[str] = None

class SmsEvent(WebhookEvent):
    channel: Literal["sms"]

class EmailEvent(WebhookEvent):
    channel: Literal["email"]

class VoiceEvent(WebhookEvent):
    channel: Literal["voice"]
