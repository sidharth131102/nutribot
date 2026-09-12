"""Azure OpenAI implementation of LLMProvider. The only file allowed to import langchain_openai.

Azure OpenAI addresses models by a deployment name (created in the Azure
resource), not a raw model id like Groq/Pinecone. The factory instantiates
this class twice against the same resource: the primary deployments
(settings.azure_openai_deployment_*) and, in Phase 7, the challenger
deployments (settings.azure_openai_challenger_deployment_*).

Reasoning-model vs. classic-model kwargs are driven by an explicit flag, never
inferred from the deployment-name string (names are user-chosen and unreliable
to parse).
"""
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI

from backend.config import Settings
from backend.llm.base import GenerationConfig, GenerationResult, LLMProvider, Message

_ROLE_TO_LC = {
    "system": SystemMessage,
    "user": HumanMessage,
    "assistant": AIMessage,
}


class AzureOpenAIProvider(LLMProvider):
    def __init__(
        self,
        settings: Settings,
        *,
        deployment_full: str,
        deployment_fast: str,
        reasoning_model: bool,
        provider_name: str,
    ):
        self._settings = settings  # endpoint / api_key / api_version only
        self._deployment_full = deployment_full
        self._deployment_fast = deployment_fast
        self._reasoning_model = reasoning_model
        self._provider_name = provider_name

    async def generate(self, messages: list[Message], config: GenerationConfig) -> GenerationResult:
        is_fast = config.profile == "fast"
        deployment = self._deployment_fast if is_fast else self._deployment_full

        kwargs: dict[str, Any] = {
            "azure_endpoint": self._settings.azure_openai_endpoint,
            "deployment_name": deployment,
            "openai_api_key": self._settings.azure_openai_api_key,
            "openai_api_version": self._settings.azure_openai_api_version,
            "max_tokens": config.max_tokens,
            # No explicit timeout previously -- a request silently hung for
            # hours during eval-harness testing with nothing to show for it.
            # Fail fast and loudly instead of hanging indefinitely.
            "timeout": 120,
            "max_retries": 2,
        }
        if self._reasoning_model:
            # GPT-5-family models only support the default temperature (1) --
            # passing anything else 400s, so it's omitted entirely. Same class
            # of issue as Groq's gpt-oss models: without reasoning_effort,
            # hidden chain-of-thought can consume the whole token budget before
            # any visible answer, returning empty text. "full" gets a bit more
            # room than "minimal" -- numeric-constraint tasks (hit this calorie
            # target) benefit from a little real reasoning.
            kwargs["reasoning_effort"] = "minimal" if is_fast else "low"
        else:
            # Classic chat models (gpt-4.1) reject reasoning_effort and honor
            # temperature -- the exact inverse of the reasoning branch.
            kwargs["temperature"] = config.temperature

        llm = AzureChatOpenAI(**kwargs)
        lc_messages = [_ROLE_TO_LC[m.role](content=m.content) for m in messages]
        response = await llm.ainvoke(lc_messages)
        text = response.content if isinstance(response.content, str) else str(response.content)

        return GenerationResult(text=text, model=deployment, provider=self._provider_name)
