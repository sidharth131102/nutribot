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
    # BCP-47 locale the browser's speech recognizer detected ("hi-IN") when
    # the message came from the microphone; None for typed text (auto-detected).
    language: Optional[str] = Field(default=None, max_length=16)


class ChatResponse(BaseModel):
    response: str
    intent: str
    plan_proposed: bool = False
    proposed_plan: Optional[dict[str, Any]] = None
    session_id: str
    rag_sources: list[dict[str, Any]] = Field(default_factory=list)
    # Language the response is written in (Translator code: "en", "hi", "ml", "fr").
    language: str = "en"
    # The English the pipeline actually processed, when the message was
    # translated -- lets the UI show "understood as: ..." for transparency.
    message_english: Optional[str] = None


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[ChatMessage]
