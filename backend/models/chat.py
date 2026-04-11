from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ChatSession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    started_at: datetime = Field(default_factory=datetime.utcnow)
    messages: list[ChatMessage] = Field(default_factory=list)


class ChatRequest(BaseModel):
    user_id: str
    message: str
    session_id: str


class ChatResponse(BaseModel):
    response: str
    intent: str
    plan_proposed: bool = False
    proposed_plan: Optional[dict[str, Any]] = None
    session_id: str
    rag_sources: list[dict[str, Any]] = Field(default_factory=list)


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[ChatMessage]
