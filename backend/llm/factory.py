"""Config-driven provider selection — the switch point providers plug into.

Registry values are builders (settings -> provider) rather than bare classes
so one class can be registered twice with different deployments -- the
primary and challenger Azure OpenAI entries (Phase 7) share a class but not
a configuration.
"""
from collections.abc import Callable
from functools import lru_cache

from backend.config import Settings, get_settings
from backend.llm.azure_openai_provider import AzureOpenAIProvider
from backend.llm.base import LLMProvider
from backend.llm.groq_provider import GroqProvider


def _build_groq(settings: Settings) -> LLMProvider:
    return GroqProvider(settings)


def _build_azure_openai(settings: Settings) -> LLMProvider:
    return AzureOpenAIProvider(
        settings,
        deployment_full=settings.azure_openai_deployment_full,
        deployment_fast=settings.azure_openai_deployment_fast,
        reasoning_model=settings.azure_openai_reasoning_model,
        provider_name="azure_openai",
    )


def _build_azure_openai_challenger(settings: Settings) -> LLMProvider:
    missing = [
        env
        for env, value in (
            ("AZURE_OPENAI_CHALLENGER_DEPLOYMENT_FULL", settings.azure_openai_challenger_deployment_full),
            ("AZURE_OPENAI_CHALLENGER_DEPLOYMENT_FAST", settings.azure_openai_challenger_deployment_fast),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            "Provider 'azure_openai_challenger' is not configured -- set " + ", ".join(missing)
        )
    return AzureOpenAIProvider(
        settings,
        deployment_full=settings.azure_openai_challenger_deployment_full,
        deployment_fast=settings.azure_openai_challenger_deployment_fast,
        reasoning_model=settings.azure_openai_challenger_reasoning_model,
        provider_name="azure_openai_challenger",
    )


_PROVIDERS: dict[str, Callable[[Settings], LLMProvider]] = {
    "groq": _build_groq,
    "azure_openai": _build_azure_openai,
    "azure_openai_challenger": _build_azure_openai_challenger,
}


@lru_cache
def get_provider(name: str | None = None) -> LLMProvider:
    """None -> settings.llm_provider (what every agent uses). An explicit name
    -> that registry entry regardless of the active provider (used to pin the
    eval judge and to drive `--compare` arms).

    Cache semantics: lru_cache keys the zero-arg call as () and get_provider("x")
    as ("x",), so the zero-arg entry snapshots settings.llm_provider at first
    use -- anything that mutates llm_provider afterwards (compare mode, tests)
    must call get_provider.cache_clear().
    """
    settings = get_settings()
    resolved = name or settings.llm_provider
    try:
        builder = _PROVIDERS[resolved]
    except KeyError:
        raise ValueError(
            f"Unknown LLM provider {resolved!r}; expected one of {sorted(_PROVIDERS)}"
        ) from None
    return builder(settings)
