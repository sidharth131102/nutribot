"""Tests for backend/eval/deepeval_provider.py -- confirms NutriBotDeepEvalLLM
routes every call through get_provider(), never a vendor SDK directly
(invariant 6), and that the judge is pinned to eval_judge_provider rather
than floating with the active llm_provider (Phase 7). No real LLM calls."""
import pytest

from backend.config import get_settings
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
    monkeypatch.setattr("backend.eval.deepeval_provider.get_provider", lambda name=None: fake_provider)

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
    monkeypatch.setattr("backend.eval.deepeval_provider.get_provider", lambda name=None: fake_provider)

    llm = NutriBotDeepEvalLLM()
    await llm.a_generate("some prompt")

    assert fake_provider.received_config.profile == "full"
    assert fake_provider.received_config.temperature == 0


@pytest.mark.asyncio
async def test_judge_is_pinned_to_eval_judge_provider_not_active_provider(monkeypatch):
    # The active provider is the challenger (as it is during a --compare arm),
    # but the judge must still resolve the pinned primary -- otherwise the
    # challenger would be judging its own output.
    settings = get_settings()
    monkeypatch.setattr(settings, "eval_judge_provider", "azure_openai")
    monkeypatch.setattr(settings, "llm_provider", "azure_openai_challenger")

    seen_names = []
    fake_provider = _FakeProvider()

    def _capture(name=None):
        seen_names.append(name)
        return fake_provider

    monkeypatch.setattr("backend.eval.deepeval_provider.get_provider", _capture)

    await NutriBotDeepEvalLLM().a_generate("some prompt")

    assert seen_names == ["azure_openai"]


def test_load_model_returns_self():
    llm = NutriBotDeepEvalLLM()
    assert llm.load_model() is llm


def test_get_model_name_reports_pinned_judge_provider(monkeypatch):
    monkeypatch.setattr(get_settings(), "eval_judge_provider", "azure_openai")

    llm = NutriBotDeepEvalLLM()
    assert llm.get_model_name() == "nutribot-azure_openai"


def test_sync_generate_delegates_to_a_generate(monkeypatch):
    fake_provider = _FakeProvider()
    monkeypatch.setattr("backend.eval.deepeval_provider.get_provider", lambda name=None: fake_provider)

    llm = NutriBotDeepEvalLLM()
    result = llm.generate("some prompt")

    assert result == "fake response"
