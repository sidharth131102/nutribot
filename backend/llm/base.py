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
