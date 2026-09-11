"""Tests for backend/eval/scorers/deterministic.py -- the food_context-
fallback allergen heuristic (word-boundary, not bare substring). No LLM
calls, no live credentials.
"""
from backend.eval.models import GoldenCase
from backend.eval.scorers.deterministic import score_deterministic


def _case(allergies, expect_plan=True):
    return GoldenCase(
        id="test-case",
        category="allergy_diet_edge_case",
        profile={"allergies": allergies},
        user_message="test",
        expect_plan=expect_plan,
    )


def _state_with_plan_item(food_name):
    return {
        "response": "Here is your plan.",
        "plan_proposed": True,
        "proposed_plan": {
            "days": [{"day": "Day 1", "meals": [{"items": [{"food": food_name, "calories": 100}]}]}]
        },
        "food_context": [],  # empty -- forces the no-structured-match fallback heuristic
    }


def test_coconut_does_not_false_positive_for_nut_allergy():
    # "nut" as a bare substring matches "coconut" -- coconut is not a tree
    # nut and is common in vegan/Indian cooking; this must not be flagged.
    result = score_deterministic(_case(["nut"]), _state_with_plan_item("coconut milk"))
    assert result.passed is True


def test_whole_word_allergen_match_still_flagged():
    result = score_deterministic(_case(["milk"]), _state_with_plan_item("soy milk"))
    assert result.passed is False
    assert any("milk" in f for f in result.failures)


def test_exact_allergen_food_still_flagged():
    result = score_deterministic(_case(["peanuts"]), _state_with_plan_item("peanuts"))
    assert result.passed is False


def test_no_allergy_no_failure():
    result = score_deterministic(_case([]), _state_with_plan_item("coconut milk"))
    assert result.passed is True
