"""Tests for backend/llm/azure_openai_provider.py -- the reasoning-vs-classic
kwargs branch and per-instance deployment/provider naming (Phase 7).

AzureChatOpenAI is replaced with a fake that records its constructor kwargs;
no network, no credentials. Settings is built with _env_file=None so the
local .env never leaks into these assertions.
"""
from types import SimpleNamespace

import pytest

from backend.config import Settings
from backend.llm import azure_openai_provider
from backend.llm.azure_openai_provider import AzureOpenAIProvider
from backend.llm.base import GenerationConfig, Message


class _FakeAzureChatOpenAI:
    instances: list["_FakeAzureChatOpenAI"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        _FakeAzureChatOpenAI.instances.append(self)

    async def ainvoke(self, messages):
        return SimpleNamespace(content="ok")


@pytest.fixture(autouse=True)
def _fake_llm(monkeypatch):
    _FakeAzureChatOpenAI.instances.clear()
    monkeypatch.setattr(azure_openai_provider, "AzureChatOpenAI", _FakeAzureChatOpenAI)
    yield
    _FakeAzureChatOpenAI.instances.clear()


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        azure_openai_endpoint="https://example.openai.azure.com",
        azure_openai_api_key="test-key",
        azure_openai_api_version="2024-10-21",
    )


def _provider(reasoning_model: bool, provider_name: str = "arm") -> AzureOpenAIProvider:
    return AzureOpenAIProvider(
        _settings(),
        deployment_full="dep-full",
        deployment_fast="dep-fast",
        reasoning_model=reasoning_model,
        provider_name=provider_name,
    )


async def _generate(provider: AzureOpenAIProvider, profile: str, temperature: float = 0.3):
    return await provider.generate(
        [Message(role="user", content="hi")],
        GenerationConfig(profile=profile, temperature=temperature, max_tokens=77),
    )


def _last_kwargs() -> dict:
    return _FakeAzureChatOpenAI.instances[-1].kwargs


# ── Reasoning-model branch (gpt-5 family) ─────────────────────────────────

@pytest.mark.asyncio
async def test_reasoning_full_passes_low_effort_and_no_temperature():
    await _generate(_provider(reasoning_model=True), "full")
    kwargs = _last_kwargs()
    assert kwargs["reasoning_effort"] == "low"
    assert "temperature" not in kwargs
    assert kwargs["deployment_name"] == "dep-full"


@pytest.mark.asyncio
async def test_reasoning_fast_passes_minimal_effort_and_fast_deployment():
    await _generate(_provider(reasoning_model=True), "fast")
    kwargs = _last_kwargs()
    assert kwargs["reasoning_effort"] == "minimal"
    assert "temperature" not in kwargs
    assert kwargs["deployment_name"] == "dep-fast"


# ── Classic-model branch (gpt-4.1) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_classic_passes_temperature_and_no_reasoning_effort():
    await _generate(_provider(reasoning_model=False), "full", temperature=0.42)
    kwargs = _last_kwargs()
    assert kwargs["temperature"] == 0.42
    assert "reasoning_effort" not in kwargs


@pytest.mark.asyncio
async def test_branch_is_driven_by_flag_not_deployment_name():
    # A gpt-5-looking deployment name with reasoning_model=False must still
    # take the classic branch -- the flag is authoritative, never the string.
    provider = AzureOpenAIProvider(
        _settings(),
        deployment_full="gpt-5-mini",
        deployment_fast="gpt-5-mini",
        reasoning_model=False,
        provider_name="arm",
    )
    await _generate(provider, "full")
    kwargs = _last_kwargs()
    assert "temperature" in kwargs
    assert "reasoning_effort" not in kwargs


# ── Always-present kwargs ────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("reasoning_model", [True, False])
async def test_timeout_retries_tokens_and_connection_always_set(reasoning_model):
    await _generate(_provider(reasoning_model=reasoning_model), "full")
    kwargs = _last_kwargs()
    assert kwargs["timeout"] == 120
    assert kwargs["max_retries"] == 2
    assert kwargs["max_tokens"] == 77
    assert kwargs["azure_endpoint"] == "https://example.openai.azure.com"
    assert kwargs["openai_api_key"] == "test-key"
    assert kwargs["openai_api_version"] == "2024-10-21"


# ── Result identity ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_result_reports_provider_name_and_chosen_deployment():
    result = await _generate(_provider(reasoning_model=True, provider_name="azure_openai_challenger"), "fast")
    assert result.provider == "azure_openai_challenger"
    assert result.model == "dep-fast"
    assert result.text == "ok"


# ── Content filter detection/translation ──────────────────────────────────

from backend.llm.azure_openai_provider import _raise_if_content_filtered
from backend.llm.base import ContentFilterBlocked


def test_raise_if_content_filtered_is_a_noop_for_unrelated_errors():
    exc = RuntimeError("connection reset")
    _raise_if_content_filtered(exc)  # must not raise


def test_raise_if_content_filtered_parses_flagged_categories():
    # Shape of the real Azure error body (see the docstring in
    # azure_openai_provider.py) -- self_harm flagged, others not.
    body = (
        "Error code: 400 - {'error': {'code': 'content_filter', 'innererror': "
        "{'content_filter_result': {'hate': {'filtered': False, 'severity': 'safe'}, "
        "'self_harm': {'filtered': True, 'severity': 'medium'}, "
        "'sexual': {'filtered': False, 'severity': 'safe'}, "
        "'violence': {'filtered': False, 'severity': 'safe'}}}}}"
    )
    with pytest.raises(ContentFilterBlocked) as exc_info:
        _raise_if_content_filtered(RuntimeError(body))
    assert exc_info.value.flagged_categories == ["self_harm"]


def test_raise_if_content_filtered_preserves_the_original_as_cause():
    original = RuntimeError("content_filter: self_harm flagged 'self_harm': {'filtered': True}")
    with pytest.raises(ContentFilterBlocked) as exc_info:
        _raise_if_content_filtered(original)
    assert exc_info.value.__cause__ is original


@pytest.mark.asyncio
async def test_generate_translates_a_content_filter_error(monkeypatch):
    class _RaisingAzureChatOpenAI(_FakeAzureChatOpenAI):
        async def ainvoke(self, messages):
            raise RuntimeError(
                "Error code: 400 - {'error': {'code': 'content_filter', 'innererror': "
                "{'content_filter_result': {'self_harm': {'filtered': True, 'severity': 'medium'}}}}}"
            )

    monkeypatch.setattr(azure_openai_provider, "AzureChatOpenAI", _RaisingAzureChatOpenAI)

    with pytest.raises(ContentFilterBlocked) as exc_info:
        await _generate(_provider(reasoning_model=True), "fast")
    assert exc_info.value.flagged_categories == ["self_harm"]


@pytest.mark.asyncio
async def test_generate_propagates_unrelated_errors_unchanged(monkeypatch):
    class _RaisingAzureChatOpenAI(_FakeAzureChatOpenAI):
        async def ainvoke(self, messages):
            raise TimeoutError("upstream timed out")

    monkeypatch.setattr(azure_openai_provider, "AzureChatOpenAI", _RaisingAzureChatOpenAI)

    with pytest.raises(TimeoutError):
        await _generate(_provider(reasoning_model=True), "fast")
