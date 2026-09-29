"""Generation-provider abstraction. No agent may import a vendor SDK directly — only implementations in this package may."""
from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class GenerationConfig(BaseModel):
    profile: Literal["fast", "full"] = "full"
    temperature: float = 0.7
    max_tokens: int = 1024


class GenerationResult(BaseModel):
    text: str
    model: str
    provider: str


class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, messages: list[Message], config: GenerationConfig) -> GenerationResult:
        ...


class ContentFilterBlocked(Exception):
    """Raised when the provider's own platform-level content filter (e.g.
    Azure's Responsible AI policy) rejected a request outright, before the
    model ever produced output -- provider-agnostic so callers never need
    to know which vendor exception shape triggered it.

    This is a materially different situation from a generic provider
    failure (timeout, bad config, transient API error): the platform
    itself judged the *input* concerning enough to refuse processing it.
    A caller making a safety decision -- the input guardrail is the one
    that matters here -- should treat this as a strong positive signal for
    the category involved, not fail open the way it would for an ordinary
    error. Found live: a message worded like genuine self-harm ideation
    tripped Azure's filter and, because `check_input`'s exception handler
    failed open unconditionally, would have silently passed through as
    "not blocked" instead of showing the crisis-line response.
    """

    def __init__(self, flagged_categories: list[str]):
        self.flagged_categories = flagged_categories
        super().__init__(f"Content filtered: {', '.join(flagged_categories) or 'unknown category'}")
