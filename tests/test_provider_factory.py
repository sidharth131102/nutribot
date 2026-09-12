"""Tests for backend/llm/factory.py -- registry resolution, challenger
configuration errors, explicit-name pinning, and cache semantics (Phase 7).

Providers are only constructed here, never invoked, so nothing touches the
network. Settings fields are set explicitly per test because the live .env
may or may not have challenger deployments configured.
"""
import pytest

from backend.config import get_settings
from backend.llm.azure_openai_provider import AzureOpenAIProvider
from backend.llm.factory import get_provider
from backend.llm.groq_provider import GroqProvider


@pytest.fixture(autouse=True)
def _clean_cache_and_settings(monkeypatch):
    get_provider.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "azure_openai")
    monkeypatch.setattr(settings, "azure_openai_reasoning_model", True)
    monkeypatch.setattr(settings, "azure_openai_challenger_deployment_full", "")
    monkeypatch.setattr(settings, "azure_openai_challenger_deployment_fast", "")
    monkeypatch.setattr(settings, "azure_openai_challenger_reasoning_model", False)
    yield
    get_provider.cache_clear()


def _configure_challenger(monkeypatch, full="gpt-4-1", fast="gpt-4-1"):
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_challenger_deployment_full", full)
    monkeypatch.setattr(settings, "azure_openai_challenger_deployment_fast", fast)


# ── Challenger configuration ─────────────────────────────────────────────

def test_challenger_unconfigured_raises_naming_both_env_vars():
    with pytest.raises(ValueError) as excinfo:
        get_provider("azure_openai_challenger")
    message = str(excinfo.value)
    assert "AZURE_OPENAI_CHALLENGER_DEPLOYMENT_FULL" in message
    assert "AZURE_OPENAI_CHALLENGER_DEPLOYMENT_FAST" in message


def test_challenger_only_fast_missing_names_only_fast(monkeypatch):
    _configure_challenger(monkeypatch, full="gpt-4-1", fast="")
    with pytest.raises(ValueError) as excinfo:
        get_provider("azure_openai_challenger")
    message = str(excinfo.value)
    assert "AZURE_OPENAI_CHALLENGER_DEPLOYMENT_FAST" in message
    assert "AZURE_OPENAI_CHALLENGER_DEPLOYMENT_FULL" not in message


def test_challenger_configured_builds_azure_instance_with_challenger_fields(monkeypatch):
    _configure_challenger(monkeypatch)
    provider = get_provider("azure_openai_challenger")
    assert isinstance(provider, AzureOpenAIProvider)
    assert provider._deployment_full == "gpt-4-1"
    assert provider._deployment_fast == "gpt-4-1"
    assert provider._reasoning_model is False
    assert provider._provider_name == "azure_openai_challenger"


# ── Default resolution follows settings.llm_provider ─────────────────────

def test_default_resolves_primary_azure_with_primary_fields():
    provider = get_provider()
    assert isinstance(provider, AzureOpenAIProvider)
    assert provider._provider_name == "azure_openai"
    assert provider._reasoning_model is True
    assert provider._deployment_full == get_settings().azure_openai_deployment_full


def test_default_resolves_groq_when_selected(monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_provider", "groq")
    assert isinstance(get_provider(), GroqProvider)


# ── Explicit-name pinning ────────────────────────────────────────────────

def test_explicit_name_pins_regardless_of_active_provider():
    # Active provider is azure_openai (fixture); an explicit name wins.
    assert isinstance(get_provider("groq"), GroqProvider)
    assert isinstance(get_provider(), AzureOpenAIProvider)


def test_unknown_name_raises_clear_error():
    with pytest.raises(ValueError, match="nope"):
        get_provider("nope")


# ── Cache semantics ──────────────────────────────────────────────────────

def test_cache_returns_same_instance_until_cleared(monkeypatch):
    first = get_provider()
    assert get_provider() is first

    monkeypatch.setattr(get_settings(), "llm_provider", "groq")
    # Still cached -- the zero-arg entry snapshotted the old llm_provider.
    assert get_provider() is first

    get_provider.cache_clear()
    assert isinstance(get_provider(), GroqProvider)
