from pydantic import BaseModel, Field
from typing import Any, Dict

class ProviderEvent(BaseModel):
    status: str = Field(..., examples=["delivered", "failed", "replied"])
    provider_ref: str = Field(..., examples=["abc123"])
    data: Dict[str, Any] = Field(default_factory=dict)  # raw provider payload
