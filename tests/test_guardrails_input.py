"""Tests for backend/guardrails/input_check.py -- category->canned-response
mapping, fail-open behavior, and routing. No real LLM calls."""
import pytest

from backend.agents.graph import _route_after_input_guardrail
from backend.guardrails.input_check import CATEGORY_RESPONSES, _extract_category, check_input


# ── _extract_category ────────────────────────────────────────────────────────

def test_extract_category_parses_valid_json():
    assert _extract_category('{"category": "SELF_HARM"}') == "SELF_HARM"


def test_extract_category_parses_none():
    assert _extract_category('{"category": "NONE"}') == "NONE"


def test_extract_category_returns_none_for_unknown_category():
    assert _extract_category('{"category": "SOMETHING_ELSE"}') is None


def test_extract_category_returns_none_for_malformed_json():
    assert _extract_category('{"category": "SELF_HARM"') is None


def test_extract_category_returns_none_for_no_json():
    assert _extract_category("no json here") is None


# ── Canned responses are never LLM text ──────────────────────────────────────

def test_every_non_none_category_has_a_canned_response():
    for category in ("MEDICAL_EMERGENCY", "MEDICATION_MISUSE", "SELF_HARM"):
        assert category in CATEGORY_RESPONSES
        assert len(CATEGORY_RESPONSES[category]) > 20


# ── check_input: fail-open behavior ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_input_fails_open_on_provider_error(monkeypatch):
    def _raise():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("backend.guardrails.input_check.get_provider", _raise)

    result = await check_input("what should I eat for breakfast?")

    assert result.blocked is False
    assert result.category == "NONE"


@pytest.mark.asyncio
async def test_check_input_fails_open_on_unparseable_response(monkeypatch):
    class _FakeResult:
        text = "I'm not sure how to classify this."

    class _FakeProvider:
        async def generate(self, **kwargs):
            return _FakeResult()

    monkeypatch.setattr("backend.guardrails.input_check.get_provider", lambda: _FakeProvider())

    result = await check_input("some message")

    assert result.blocked is False


@pytest.mark.asyncio
async def test_check_input_blocks_on_classified_category(monkeypatch):
    class _FakeResult:
        text = '{"category": "MEDICATION_MISUSE"}'

    class _FakeProvider:
        async def generate(self, **kwargs):
            return _FakeResult()

    monkeypatch.setattr("backend.guardrails.input_check.get_provider", lambda: _FakeProvider())

    result = await check_input("can I take 5x my prescribed dose?")

    assert result.blocked is True
    assert result.category == "MEDICATION_MISUSE"
    assert result.canned_response == CATEGORY_RESPONSES["MEDICATION_MISUSE"]


@pytest.mark.asyncio
async def test_check_input_does_not_block_on_none_category(monkeypatch):
    class _FakeResult:
        text = '{"category": "NONE"}'

    class _FakeProvider:
        async def generate(self, **kwargs):
            return _FakeResult()

    monkeypatch.setattr("backend.guardrails.input_check.get_provider", lambda: _FakeProvider())

    result = await check_input("what's a good high protein breakfast?")

    assert result.blocked is False


# ── Routing ───────────────────────────────────────────────────────────────────

def test_route_after_input_guardrail_blocked():
    assert _route_after_input_guardrail({"guardrail_blocked": True}) == "blocked"


def test_route_after_input_guardrail_continue():
    assert _route_after_input_guardrail({"guardrail_blocked": False}) == "continue"


def test_route_after_input_guardrail_defaults_to_continue():
    assert _route_after_input_guardrail({}) == "continue"
