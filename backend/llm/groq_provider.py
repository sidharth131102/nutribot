"""Groq implementation of LLMProvider. The only file allowed to import langchain_groq."""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from backend.config import Settings
from backend.llm.base import GenerationConfig, GenerationResult, LLMProvider, Message

_ROLE_TO_LC = {
    "system": SystemMessage,
    "user": HumanMessage,
    "assistant": AIMessage,
}


class GroqProvider(LLMProvider):
    def __init__(self, settings: Settings):
        self._settings = settings

    async def generate(self, messages: list[Message], config: GenerationConfig) -> GenerationResult:
        model_name = (
            self._settings.llm_model_fast if config.profile == "fast" else self._settings.llm_model
        )
        llm = ChatGroq(
            model=model_name,
            api_key=self._settings.groq_api_key,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            # GPT-OSS models spend part of the token budget on hidden chain-of-thought
            # before the visible answer — keep it low since none of our tasks need deep reasoning.
            reasoning_effort="low",
        )
        lc_messages = [_ROLE_TO_LC[m.role](content=m.content) for m in messages]
        response = await llm.ainvoke(lc_messages)
        text = response.content if isinstance(response.content, str) else str(response.content)

        return GenerationResult(text=text, model=model_name, provider="groq")
