"""Config-driven provider selection — the switch point future providers (e.g. Azure AI Foundry) plug into."""
from functools import lru_cache

from backend.config import get_settings
from backend.llm.base import LLMProvider
from backend.llm.groq_provider import GroqProvider

_PROVIDERS = {
    "groq": GroqProvider,
}


@lru_cache
def get_provider() -> LLMProvider:
    settings = get_settings()
    provider_cls = _PROVIDERS[settings.llm_provider]
    return provider_cls(settings)
