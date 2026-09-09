"""Tests for backend/guardrails/output_check.py and nodes.py -- deterministic
allergen scan, combined safe logic, regeneration cap, routing. No real LLM calls."""
import pytest

from backend.agents.graph import _route_after_meal_plan, _route_after_output_guardrail
from backend.guardrails.nodes import MAX_OUTPUT_REGENERATIONS, OUTPUT_FALLBACK_RESPONSE, output_guardrail_node
from backend.guardrails.output_check import _scan_allergens_in_prose, check_output


# ── Deterministic allergen scan ──────────────────────────────────────────────

def test_scan_detects_allergen_mention():
    hits = _scan_allergens_in_prose("This meal includes peanuts as a topping.", ["peanuts"])
    assert hits == ["peanuts"]


def test_scan_ignores_negated_mention():
    hits = _scan_allergens_in_prose("Please avoid peanuts and tree nuts in this plan.", ["peanuts"])
    assert hits == []


def test_scan_ignores_far_away_negation():
    # "avoid" is well outside the lookback window relative to "peanuts"
    text = "avoid " + ("x" * 40) + " I've added peanuts to your breakfast."
    hits = _scan_allergens_in_prose(text, ["peanuts"])
    assert hits == ["peanuts"]


def test_scan_returns_empty_for_no_hit():
    assert _scan_allergens_in_prose("This meal includes rice and lentils.", ["peanuts"]) == []


def test_scan_handles_multiple_allergies():
    hits = _scan_allergens_in_prose("Contains milk and peanuts.", ["milk", "peanuts", "shellfish"])
    assert set(hits) == {"milk", "peanuts"}


def test_scan_handles_empty_allergy_list():
    assert _scan_allergens_in_prose("Any text here.", []) == []


# ── check_output: fail-open + combined safety logic ──────────────────────────

@pytest.mark.asyncio
async def test_check_output_fails_open_on_provider_error(monkeypatch):
    def _raise():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("backend.guardrails.output_check.get_provider", _raise)

    result = await check_output("A safe response.", None, [], [], [])

    assert result.safe is True


@pytest.mark.asyncio
async def test_check_output_allergen_hit_overrides_llm_safe(monkeypatch):
    class _FakeResult:
        text = '{"safe": true, "issues": [], "feedback": ""}'

    class _FakeProvider:
        async def generate(self, **kwargs):
            return _FakeResult()

    monkeypatch.setattr("backend.guardrails.output_check.get_provider", lambda: _FakeProvider())

    result = await check_output("This includes peanuts.", None, [], ["peanuts"], [])

    assert result.safe is False
    assert any("peanuts" in issue for issue in result.issues)


@pytest.mark.asyncio
async def test_check_output_llm_unsafe_result(monkeypatch):
    class _FakeResult:
        text = '{"safe": false, "issues": ["diagnosis language"], "feedback": "Remove the diagnosis claim."}'

    class _FakeProvider:
        async def generate(self, **kwargs):
            return _FakeResult()

    monkeypatch.setattr("backend.guardrails.output_check.get_provider", lambda: _FakeProvider())

    result = await check_output("You definitely have diabetes.", None, [], [], ["diabetes"])

    assert result.safe is False
    assert "diagnosis language" in result.issues


@pytest.mark.asyncio
async def test_check_output_safe_when_no_issues(monkeypatch):
    class _FakeResult:
        text = '{"safe": true, "issues": [], "feedback": ""}'

    class _FakeProvider:
        async def generate(self, **kwargs):
            return _FakeResult()

    monkeypatch.setattr("backend.guardrails.output_check.get_provider", lambda: _FakeProvider())

    result = await check_output("Here's a balanced breakfast idea.", None, [], [], [])

    assert result.safe is True


# ── output_guardrail_node: regeneration cap ──────────────────────────────────

@pytest.mark.asyncio
async def test_output_guardrail_node_passes_through_when_safe(monkeypatch):
    async def _fake_check_output(**kwargs):
        from backend.guardrails.models import OutputCheckResult
        return OutputCheckResult(safe=True)

    monkeypatch.setattr("backend.guardrails.nodes.check_output", _fake_check_output)

    state = {"response": "fine", "user_profile": {}}
    result = await output_guardrail_node(state)

    assert result["guardrail_output_ok"] is True
    assert result["guardrail_blocked"] is False


@pytest.mark.asyncio
async def test_output_guardrail_node_regenerates_under_cap(monkeypatch):
    async def _fake_check_output(**kwargs):
        from backend.guardrails.models import OutputCheckResult
        return OutputCheckResult(safe=False, issues=["bad"], feedback="fix it")

    monkeypatch.setattr("backend.guardrails.nodes.check_output", _fake_check_output)

    state = {"response": "bad", "user_profile": {}, "guardrail_regeneration_count": 0}
    result = await output_guardrail_node(state)

    assert result["guardrail_output_ok"] is False
    assert result["guardrail_blocked"] is False
    assert result["guardrail_regeneration_count"] == 1
    assert result["guardrail_feedback"] == "fix it"


@pytest.mark.asyncio
async def test_output_guardrail_node_falls_back_at_cap(monkeypatch):
    async def _fake_check_output(**kwargs):
        from backend.guardrails.models import OutputCheckResult
        return OutputCheckResult(safe=False, issues=["still bad"], feedback="fix it again")

    monkeypatch.setattr("backend.guardrails.nodes.check_output", _fake_check_output)

    state = {"response": "still bad", "user_profile": {}, "guardrail_regeneration_count": MAX_OUTPUT_REGENERATIONS}
    result = await output_guardrail_node(state)

    assert result["guardrail_output_ok"] is False
    assert result["guardrail_blocked"] is True
    assert result["response"] == OUTPUT_FALLBACK_RESPONSE
    assert result["plan_proposed"] is False
    assert result["proposed_plan"] is None


# ── Routing ───────────────────────────────────────────────────────────────────

def test_route_after_output_guardrail_regenerates():
    assert _route_after_output_guardrail({"guardrail_output_ok": False, "guardrail_blocked": False}) == "regenerate"


def test_route_after_output_guardrail_delegates_when_ok():
    state = {"guardrail_output_ok": True, "intent": "GENERAL_CONVERSATION", "user_message": "hi"}
    assert _route_after_output_guardrail(state) == "end"


def test_route_after_output_guardrail_delegates_when_blocked():
    state = {"guardrail_output_ok": False, "guardrail_blocked": True, "intent": "GENERAL_CONVERSATION", "user_message": "hi"}
    assert _route_after_output_guardrail(state) == "end"


def test_route_after_meal_plan_short_circuits_when_blocked():
    assert _route_after_meal_plan({"guardrail_blocked": True, "intent": "PLAN_MODIFICATION", "user_message": "I prefer chicken"}) == "end"
