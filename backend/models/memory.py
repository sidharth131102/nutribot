from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

MemoryCategory = Literal["preference", "dislike", "goal_context", "lifestyle"]
MemoryStatus = Literal["active", "superseded"]
EventType = Literal["goal_change", "plan_accepted"]


class MemoryFact(BaseModel):
    user_id: str
    fact: str
    category: MemoryCategory
    source: str = "chat_extraction"
    confidence: float = Field(ge=0.0, le=1.0, default=0.7)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_confirmed: datetime = Field(default_factory=datetime.utcnow)
    status: MemoryStatus = "active"
    superseded_by: Optional[str] = None


class EpisodicEvent(BaseModel):
    user_id: str
    event_type: EventType
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ExtractedFact(BaseModel):
    """LLM extraction output -- fact is None when nothing's worth persisting."""
    fact: Optional[str] = None
    category: Optional[MemoryCategory] = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.7)
