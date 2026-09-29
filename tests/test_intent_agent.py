"""Tests for backend/agents/intent_agent.py.

Regression coverage for a real bug: a meta/about-the-app question ("what is
a personal nutrition companion?") was classified as NUTRITION_QUESTION
because the word "nutrition" appeared in it. That pulled in irrelevant RAG
context, which led the model to mention an unrelated food and trip the
allergen guardrail on an off-topic question -- a confusing, ~45s round trip
for what should have been a one-line answer. Fixed by sharpening the
prompt's GENERAL_CONVERSATION/NUTRITION_QUESTION boundary.
"""
import pytest

from backend.agents import intent_agent as agent
from backend.agents.intent_agent import intent_agent_node
from backend.llm.base import GenerationResult


class FakeProvider:
    def __init__(self, text=None, exc=None):
        self.text = text
        self.exc = exc
        self.calls = []

    async def generate(self, messages, config):
        self.calls.append({"messages": messages, "config": config})
        if self.exc:
            raise self.exc
        return GenerationResult(text=self.text, model="fake", provider="fake")


@pytest.fixture
def use_fake(monkeypatch):
    def _install(**kwargs):
        fake = FakeProvider(**kwargs)
        monkeypatch.setattr(agent, "get_provider", lambda name=None: fake)
        return fake
    return _install


@pytest.mark.asyncio
async def test_meta_question_about_the_app_is_general_conversation(use_fake):
    """The prompt itself must draw this distinction -- assert the system
    prompt actually instructs it, since the classifier is an LLM call we
    can't unit-test end-to-end without a live model."""
    use_fake(text="GENERAL_CONVERSATION")
    result = await intent_agent_node({"user_message": "What is a personal nutrition companion?"})
    assert result["intent"] == "GENERAL_CONVERSATION"


@pytest.mark.asyncio
async def test_real_nutrition_question_still_classifies_correctly(use_fake):
    use_fake(text="NUTRITION_QUESTION")
    result = await intent_agent_node({"user_message": "How much protein should I eat daily?"})
    assert result["intent"] == "NUTRITION_QUESTION"


def test_prompt_distinguishes_app_questions_from_nutrition_questions():
    prompt = agent.SYSTEM_PROMPT
    assert "nutrition companion" in prompt.lower()
    assert "GENERAL_CONVERSATION" in prompt
    # The exact bug that was hit: routes to GENERAL_CONVERSATION, not just present as an example.
    assert '"What is a personal nutrition companion?" -> GENERAL_CONVERSATION' in prompt


@pytest.mark.asyncio
async def test_invalid_llm_output_falls_back_to_general_conversation(use_fake):
    use_fake(text="NOT_A_REAL_INTENT")
    result = await intent_agent_node({"user_message": "hello"})
    assert result["intent"] == "GENERAL_CONVERSATION"


@pytest.mark.asyncio
async def test_provider_failure_falls_back_to_general_conversation(use_fake):
    use_fake(exc=RuntimeError("provider down"))
    result = await intent_agent_node({"user_message": "hello"})
    assert result["intent"] == "GENERAL_CONVERSATION"


@pytest.mark.asyncio
async def test_intent_is_stripped_and_uppercased(use_fake):
    use_fake(text="  meal_plan_request  \n")
    result = await intent_agent_node({"user_message": "give me a plan"})
    assert result["intent"] == "MEAL_PLAN_REQUEST"


@pytest.mark.asyncio
async def test_uses_fast_profile_and_zero_temperature(use_fake):
    fake = use_fake(text="GENERAL_CONVERSATION")
    await intent_agent_node({"user_message": "hi"})
    assert fake.calls[0]["config"].profile == "fast"
    assert fake.calls[0]["config"].temperature == 0


# ── fast_call_provider pinning ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_uses_primary_when_fast_call_provider_unset(monkeypatch):
    from backend.config import Settings

    seen = {}

    def _get_provider(name=None):
        seen["name"] = name
        return FakeProvider(text="GENERAL_CONVERSATION")

    monkeypatch.setattr(agent, "get_provider", _get_provider)
    monkeypatch.setattr(agent, "get_settings", lambda: Settings(_env_file=None, fast_call_provider=""))

    await intent_agent_node({"user_message": "hi"})

    assert seen["name"] is None


@pytest.mark.asyncio
async def test_pins_to_configured_fast_call_provider(monkeypatch):
    from backend.config import Settings

    seen = {}

    def _get_provider(name=None):
        seen["name"] = name
        return FakeProvider(text="GENERAL_CONVERSATION")

    monkeypatch.setattr(agent, "get_provider", _get_provider)
    monkeypatch.setattr(
        agent, "get_settings", lambda: Settings(_env_file=None, fast_call_provider="azure_openai_challenger")
    )

    await intent_agent_node({"user_message": "hi"})

    assert seen["name"] == "azure_openai_challenger"
