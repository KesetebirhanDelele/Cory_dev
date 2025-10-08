from __future__ import annotations
from typing import Literal, Optional, Any, Dict
from pydantic import BaseModel, Field

Direction = Literal["inbound", "outbound"]

class MessageDTO(BaseModel):
    provider_ref: str
    direction: Direction
    project_id: Optional[str] = None  # UUID as string
    provider_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)

class EventDTO(BaseModel):
    provider_ref: str
    direction: Direction
    type: str
    project_id: Optional[str] = None
    provider_id: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)

class LinkRefDTO(BaseModel):
    provider_ref: str
    workflow_id: str  # opaque (could be n8n execution id)
    project_id: Optional[str] = None
    notes: Optional[str] = None

class EnrollmentStatusDTO(BaseModel):
    enrollment_id: str
    status: str                   # source `enrollment.status`
    has_outcome: bool
    has_handoff: bool
    computed: Literal["completed", "handoff", "active", "unknown"]
