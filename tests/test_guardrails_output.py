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


def test_scan_does_not_false_positive_on_nutrition_words():
    # "nut" as a bare substring matches "nutrition"/"nutrient"/"nutritious" --
    # catastrophic for a nutrition assistant with any nut-allergic user.
    text = "Good nutrition is important. This meal has balanced nutrients and is nutritious."
    assert _scan_allergens_in_prose(text, ["nut"]) == []


def test_scan_does_not_false_positive_on_eggplant():
    assert _scan_allergens_in_prose("Try this eggplant curry with rice.", ["egg"]) == []


def test_scan_still_detects_whole_word_nut_allergen():
    assert _scan_allergens_in_prose("This recipe includes cashews and walnuts (nut).", ["nut"]) == ["nut"]


# ── "allergic to X" / "X allergy" negation (production finding) ─────────────
# A milk-allergic user asked a plain protein question; the model correctly
# steered them away from dairy sources, and the scan blocked its own correct
# answer because "allergic"/"allergy" weren't recognised as negation
# language -- only "avoid"/"without"/etc were.

def test_scan_ignores_allergic_to_phrasing():
    text = "Since you're allergic to milk, focus on chicken, fish, and lentils for protein instead."
    assert _scan_allergens_in_prose(text, ["milk"]) == []


def test_scan_ignores_trailing_allergy_phrasing():
    # The allergy word lands AFTER the allergen here, same asymmetry the
    # trailing "-free" case already handles.
    text = "Because of your milk allergy, dairy-based proteins like whey aren't a good fit."
    assert _scan_allergens_in_prose(text, ["milk"]) == []


def test_scan_ignores_sensitivity_and_intolerance_phrasing():
    assert _scan_allergens_in_prose("Given your soy sensitivity, tofu is best avoided.", ["soy"]) == []
    assert _scan_allergens_in_prose("A shellfish intolerance means skipping shrimp and crab.", ["shellfish"]) == []


def test_scan_still_flags_a_genuine_recommendation_despite_nearby_allergy_word():
    # Guard against the fix being too broad: an *unrelated* mention of the
    # word "allergy" elsewhere in the response must not blanket-suppress a
    # real recommendation of the allergen far away from it.
    text = "Allergy season aside, " + ("x" * 40) + " try adding milk to your smoothie for extra protein."
    assert _scan_allergens_in_prose(text, ["milk"]) == ["milk"]


# ── check_output: fail-open + combined safety logic ──────────────────────────

@pytest.mark.asyncio
async def test_check_output_fails_open_on_provider_error(monkeypatch):
    def _raise(name=None):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("backend.guardrails.output_check.get_provider", _raise)

    result = await check_output("A safe response.", None, [], [], [])

    assert result.safe is True


@pytest.mark.asyncio
async def test_check_output_handles_malformed_issues_type(monkeypatch):
    # "issues" as a bare string, not an array -- list("some string") would
    # silently explode into individual characters instead of failing loudly.
    class _FakeResult:
        text = '{"safe": false, "issues": "diagnosis language detected", "feedback": 123}'

    class _FakeProvider:
        async def generate(self, **kwargs):
            return _FakeResult()

    monkeypatch.setattr("backend.guardrails.output_check.get_provider", lambda name=None: _FakeProvider())

    result = await check_output("some response", None, [], [], [])

    assert result.issues == []
    assert result.feedback == ""
    assert result.safe is False


@pytest.mark.asyncio
async def test_check_output_allergen_hit_overrides_llm_safe(monkeypatch):
    class _FakeResult:
        text = '{"safe": true, "issues": [], "feedback": ""}'

    class _FakeProvider:
        async def generate(self, **kwargs):
            return _FakeResult()

    monkeypatch.setattr("backend.guardrails.output_check.get_provider", lambda name=None: _FakeProvider())

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

    monkeypatch.setattr("backend.guardrails.output_check.get_provider", lambda name=None: _FakeProvider())

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

    monkeypatch.setattr("backend.guardrails.output_check.get_provider", lambda name=None: _FakeProvider())

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


def test_scan_ignores_trailing_free_negation():
    """'soy-free' / 'nut free' is safety language with the negation AFTER the
    word -- the lookback window can't see it. Fired on a real soy-allergy plan
    in the eval harness whose prose said 'soy-free'."""
    assert _scan_allergens_in_prose("This plan is completely soy-free and vegan.", ["soy"]) == []
    assert _scan_allergens_in_prose("Nut free snacks only.", ["nut"]) == []
    # ...but "soy" followed by anything else is still a hit.
    assert _scan_allergens_in_prose("Add soy sauce to the stir-fry.", ["soy"]) == ["soy"]

# ── fast_call_provider pinning ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_output_uses_primary_when_fast_call_provider_unset(monkeypatch):
    from backend.config import Settings

    class _FakeResult:
        text = '{"safe": true, "issues": [], "feedback": ""}'

    seen = {}

    class _FakeProvider:
        async def generate(self, **kwargs):
            return _FakeResult()

    def _get_provider(name=None):
        seen["name"] = name
        return _FakeProvider()

    monkeypatch.setattr("backend.guardrails.output_check.get_provider", _get_provider)
    monkeypatch.setattr(
        "backend.guardrails.output_check.get_settings",
        lambda: Settings(_env_file=None, fast_call_provider=""),
    )

    await check_output("Here's a balanced breakfast idea.", None, [], [], [])

    assert seen["name"] is None


@pytest.mark.asyncio
async def test_check_output_pins_to_configured_fast_call_provider(monkeypatch):
    from backend.config import Settings

    class _FakeResult:
        text = '{"safe": true, "issues": [], "feedback": ""}'

    seen = {}

    class _FakeProvider:
        async def generate(self, **kwargs):
            return _FakeResult()

    def _get_provider(name=None):
        seen["name"] = name
        return _FakeProvider()

    monkeypatch.setattr("backend.guardrails.output_check.get_provider", _get_provider)
    monkeypatch.setattr(
        "backend.guardrails.output_check.get_settings",
        lambda: Settings(_env_file=None, fast_call_provider="azure_openai_challenger"),
    )

    await check_output("Here's a balanced breakfast idea.", None, [], [], [])

    assert seen["name"] == "azure_openai_challenger"
