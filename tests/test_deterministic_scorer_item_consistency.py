"""The eval-side proof of invariants 1 and 2: a plan item whose calories
weren't derived from food_db x grams is a deterministic failure."""
from backend.eval.models import GoldenCase
from backend.eval.scorers.deterministic import score_deterministic

OATS = {"id": "FOOD_001", "food": "oats", "quantity_grams": 60, "calories": 228, "protein": 8, "carbs": 40, "fat": 4}


def _case():
    return GoldenCase(id="t", category="meal_plan_request", profile={"allergies": []}, user_message="plan", expect_plan=True)


def _state(item):
    return {
        "response": "plan",
        "plan_proposed": True,
        "proposed_plan": {"days": [{"day": "Day 1", "meals": [{"items": [item]}]}]},
        "food_context": [OATS],
        "calorie_result": {},
    }


def test_db_derived_item_passes():
    result = score_deterministic(_case(), _state({"food": "oats", "quantity": "120g", "calories": 456.0}))
    assert result.passed, result.failures


def test_model_invented_calorie_figure_fails():
    result = score_deterministic(_case(), _state({"food": "oats", "quantity": "120g", "calories": 300}))
    assert not result.passed
    assert any("not computed from the database" in f for f in result.failures)


def test_item_without_parseable_quantity_is_not_checked():
    result = score_deterministic(_case(), _state({"food": "oats", "quantity": "1 bowl", "calories": 300}))
    assert result.passed, result.failures
