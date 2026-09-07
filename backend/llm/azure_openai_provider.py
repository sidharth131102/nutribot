"""Azure OpenAI implementation of LLMProvider. The only file allowed to import langchain_openai.

Azure OpenAI addresses models by a deployment name (created in the Azure
resource), not a raw model id like Groq/Pinecone -- see
settings.azure_openai_deployment_fast/_full.
"""
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
    def __init__(self, settings: Settings):
        self._settings = settings

    async def generate(self, messages: list[Message], config: GenerationConfig) -> GenerationResult:
        deployment = (
            self._settings.azure_openai_deployment_fast
            if config.profile == "fast"
            else self._settings.azure_openai_deployment_full
        )
        llm = AzureChatOpenAI(
            azure_endpoint=self._settings.azure_openai_endpoint,
            deployment_name=deployment,
            openai_api_key=self._settings.azure_openai_api_key,
            openai_api_version=self._settings.azure_openai_api_version,
            # GPT-5-family models are reasoning models and only support the
            # default temperature (1) -- passing anything else 400s. No
            # per-call temperature control for this provider.
            max_tokens=config.max_tokens,
            # Same class of issue as Groq's gpt-oss models: without this,
            # hidden chain-of-thought can consume the whole token budget
            # before any visible answer, returning empty text. "full" gets a
            # bit more room than "minimal" -- numeric-constraint tasks (hit
            # this calorie target) benefit from a little real reasoning, and
            # Azure's quota (100K+ TPM) has headroom Groq never did.
            reasoning_effort="minimal" if config.profile == "fast" else "low",
            # No explicit timeout previously -- a request silently hung for
            # hours during eval-harness testing with nothing to show for it.
            # Fail fast and loudly instead of hanging indefinitely.
            timeout=120,
            max_retries=2,
        )
        lc_messages = [_ROLE_TO_LC[m.role](content=m.content) for m in messages]
        response = await llm.ainvoke(lc_messages)
        text = response.content if isinstance(response.content, str) else str(response.content)

        return GenerationResult(text=text, model=deployment, provider="azure_openai")
