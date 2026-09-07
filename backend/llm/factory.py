"""Config-driven provider selection — the switch point providers plug into."""
from functools import lru_cache

from backend.config import get_settings
from backend.llm.azure_openai_provider import AzureOpenAIProvider
from backend.llm.base import LLMProvider
from backend.llm.groq_provider import GroqProvider

_PROVIDERS = {
    "groq": GroqProvider,
    "azure_openai": AzureOpenAIProvider,
}


@lru_cache
def get_provider() -> LLMProvider:
    settings = get_settings()
    provider_cls = _PROVIDERS[settings.llm_provider]
    return provider_cls(settings)
