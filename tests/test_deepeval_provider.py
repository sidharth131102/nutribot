"""Tests for backend/eval/deepeval_provider.py -- confirms NutriBotDeepEvalLLM
routes every call through get_provider(), never a vendor SDK directly
(invariant 6). No real LLM calls."""
import pytest

from backend.eval.deepeval_provider import NutriBotDeepEvalLLM
from backend.llm.base import GenerationResult


class _FakeProvider:
    def __init__(self):
        self.received_messages = None
        self.received_config = None

    async def generate(self, messages, config):
        self.received_messages = messages
        self.received_config = config
        return GenerationResult(text="fake response", model="fake-model", provider="fake")


@pytest.mark.asyncio
async def test_a_generate_calls_get_provider(monkeypatch):
    fake_provider = _FakeProvider()
    monkeypatch.setattr("backend.eval.deepeval_provider.get_provider", lambda: fake_provider)

    llm = NutriBotDeepEvalLLM()
    result = await llm.a_generate("classify this text")

    assert result == "fake response"
    assert fake_provider.received_messages[0].role == "user"
    assert fake_provider.received_messages[0].content == "classify this text"


@pytest.mark.asyncio
async def test_a_generate_uses_full_profile_and_zero_temperature(monkeypatch):
    # "full" (not "fast"): DeepEval's internal prompts are longer/more complex
    # than a quick classification -- "fast"'s tighter reasoning budget was
    # observed to silently return empty/truncated text for these calls.
    fake_provider = _FakeProvider()
    monkeypatch.setattr("backend.eval.deepeval_provider.get_provider", lambda: fake_provider)

    llm = NutriBotDeepEvalLLM()
    await llm.a_generate("some prompt")

    assert fake_provider.received_config.profile == "full"
    assert fake_provider.received_config.temperature == 0


def test_load_model_returns_self():
    llm = NutriBotDeepEvalLLM()
    assert llm.load_model() is llm


def test_get_model_name_includes_provider(monkeypatch):
    from backend.config import get_settings
    monkeypatch.setattr(get_settings(), "llm_provider", "azure_openai")

    llm = NutriBotDeepEvalLLM()
    assert llm.get_model_name() == "nutribot-azure_openai"


def test_sync_generate_delegates_to_a_generate(monkeypatch):
    fake_provider = _FakeProvider()
    monkeypatch.setattr("backend.eval.deepeval_provider.get_provider", lambda: fake_provider)

    llm = NutriBotDeepEvalLLM()
    result = llm.generate("some prompt")

    assert result == "fake response"
