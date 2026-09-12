"""Tests for backend/utils/food_filter.py.

Allergen/diet exclusion is the most safety-critical test in the repo per the
v2 roadmap — a bug here could serve an allergen to an allergic user.
"""
import pytest

from backend.agents.food_agent import FOOD_LIST_SIZE
from backend.eval.golden_set import GOLDEN_CASES
from backend.tools.calorie_tool import compute_calories
from backend.utils.food_filter import find_food, food_name_matches, get_filtered_foods

# Every meal slot of the day, in order; snacks appear twice because the plan
# has two snack meals.
DAY_SLOTS = ["breakfast", "snack", "lunch", "snack", "dinner"]
# Minimum distinct foods per slot for a week of varied meals.
MIN_PER_SLOT = 8


def test_allergen_exclusion_is_absolute():
    profile = {"diet_type": "vegetarian", "allergies": ["milk"], "medical_conditions": []}
    foods = get_filtered_foods(profile, limit=200)
    for food in foods:
        allergens = {a.lower() for a in food.get("allergens", [])}
        assert "milk" not in allergens, f"{food['food']} contains milk allergen but wasn't excluded"


def test_diet_type_filtering_vegan():
    profile = {"diet_type": "vegan", "allergies": [], "medical_conditions": []}
    foods = get_filtered_foods(profile, limit=200)
    assert foods, "no vegan foods returned -- sanity check on the fixture data itself"
    for food in foods:
        diets = {d.lower() for d in food.get("diet_types", [])}
        assert "vegan" in diets, f"{food['food']} is not vegan but was returned for a vegan profile"


def test_diabetes_profile_only_gets_low_or_medium_gi():
    profile = {"diet_type": "vegetarian", "allergies": [], "medical_conditions": ["diabetes"]}
    foods = get_filtered_foods(profile, limit=200)
    for food in foods:
        gi = (food.get("glycemic_index") or "").lower()
        assert gi in {"low", "very_low", "medium", ""}, f"{food['food']} has GI={gi}, unsafe for diabetic profile"


def test_hypertension_excludes_high_sodium():
    profile = {"diet_type": "vegetarian", "allergies": [], "medical_conditions": ["hypertension"]}
    foods = get_filtered_foods(profile, limit=200)
    for food in foods:
        tags = set(food.get("medical_tags", []))
        assert "high_sodium" not in tags
        assert "hypertension_avoid" not in tags


def test_kidney_condition_excludes_unsafe_foods():
    profile = {"diet_type": "vegetarian", "allergies": [], "medical_conditions": ["kidney disease"]}
    foods = get_filtered_foods(profile, limit=200)
    for food in foods:
        tags = set(food.get("medical_tags", []))
        assert "kidney_avoid" not in tags
        if float(food.get("protein", 0)) > 25:
            assert "controlled_protein" in tags


def test_selection_is_macro_diverse_not_protein_only():
    """Regression test for the calorie-undershoot fix: a flat protein-first
    ranking used to exclude carb/fat foods entirely from a small `limit`."""
    profile = {"diet_type": "non_vegetarian", "allergies": [], "medical_conditions": []}
    foods = get_filtered_foods(profile, limit=10)

    def dominant(f):
        protein_cal, carb_cal, fat_cal = f["protein"] * 4, f["carbs"] * 4, f["fat"] * 9
        top = max(protein_cal, carb_cal, fat_cal)
        if top == protein_cal:
            return "protein"
        if top == carb_cal:
            return "carb"
        return "fat"

    categories = {dominant(f) for f in foods}
    assert len(categories) > 1, "food selection is single-macro-dominant again -- diversity fix regressed"


def test_selection_respects_limit():
    profile = {"diet_type": "vegetarian", "allergies": [], "medical_conditions": []}
    assert len(get_filtered_foods(profile, limit=5)) <= 5


def _reachable_calories(foods, items_per_meal=3):
    """Best-case daily calories at DB default portions: the top-N foods
    eligible for each slot. A plan can scale portions up to 1.75x from
    there, so this only needs to be in the neighbourhood of the goal."""
    total = 0.0
    for slot in DAY_SLOTS:
        eligible = sorted(
            (f["calories"] for f in foods if slot in {m.lower() for m in f.get("meal_types", [])}),
            reverse=True,
        )
        total += sum(eligible[:items_per_meal])
    return total


_PLAN_CASES = [c for c in GOLDEN_CASES if c.expect_plan and c.profile.get("weight_kg")]


@pytest.mark.parametrize("case", _PLAN_CASES, ids=[c.id for c in _PLAN_CASES])
def test_every_meal_slot_has_enough_options_for_each_golden_profile(case):
    """Regression for the Phase 7 calorie-undershoot diagnosis: a non-veg
    muscle-gain profile used to get 19 lunch/dinner foods, 2 breakfast foods
    and 1 snack food, so 21 of the week's 35 meals had almost nothing to
    draw on."""
    foods = get_filtered_foods(case.profile, limit=FOOD_LIST_SIZE)
    for slot in set(DAY_SLOTS):
        count = sum(1 for f in foods if slot in {m.lower() for m in f.get("meal_types", [])})
        assert count >= MIN_PER_SLOT, f"{case.id}: only {count} {slot} foods in the list handed to the model"


@pytest.mark.parametrize("case", _PLAN_CASES, ids=[c.id for c in _PLAN_CASES])
def test_food_list_can_physically_reach_the_calorie_target(case):
    """The list handed to the model must be able to hit goal_calories with
    ordinary portions; otherwise no prompt wording can make a plan land."""
    foods = get_filtered_foods(case.profile, limit=FOOD_LIST_SIZE)
    goal = compute_calories(case.profile)["goal_calories"]
    reachable = _reachable_calories(foods)
    # 1.75 is plan_builder.MAX_SCALE -- what rebalancing can add on top.
    assert reachable * 1.75 >= goal * 1.1, (
        f"{case.id}: top-3-per-meal default portions reach {reachable:.0f} kcal, "
        f"goal is {goal:.0f} -- the food list starves the target"
    )


def test_selection_includes_calorie_dense_staples_not_only_protein():
    """The carb pool must contain staples (grains/roti/oats), not just dals
    -- they're what lets a day reach its target without absurd portions."""
    profile = {"diet_type": "vegetarian", "allergies": [], "medical_conditions": []}
    foods = get_filtered_foods(profile, limit=FOOD_LIST_SIZE)
    names = {f["food"] for f in foods}
    staples = {"oats", "whole wheat roti", "white rice (cooked)", "quinoa", "brown rice"}
    assert names & staples, f"no calorie-dense staple in the list: {sorted(names)}"


def test_single_meal_type_filter_still_works():
    profile = {"diet_type": "vegetarian", "allergies": [], "medical_conditions": []}
    foods = get_filtered_foods(profile, meal_type="breakfast", limit=10)
    assert foods
    for f in foods:
        assert "breakfast" in {m.lower() for m in f["meal_types"]}


# ── food_name_matches ────────────────────────────────────────────────────────

MOCK_CONTEXT = [
    {"id": "FOOD_010", "food": "turkey breast (cooked)"},
    {"id": "FOOD_001", "food": "oats"},
]


def test_food_name_matches_strips_parenthetical_qualifier():
    assert food_name_matches("Turkey breast", MOCK_CONTEXT) is True


def test_food_name_matches_exact():
    assert food_name_matches("oats", MOCK_CONTEXT) is True


def test_food_name_matches_by_id():
    assert food_name_matches("FOOD_001", MOCK_CONTEXT) is True


def test_food_name_matches_rejects_invented_food():
    assert food_name_matches("Unicorn Steak", MOCK_CONTEXT) is False


def test_food_name_matches_empty_candidate():
    assert food_name_matches("", MOCK_CONTEXT) is False


def test_find_food_prefers_exact_over_substring_match():
    """'dal' must resolve to 'dal', not to 'masoor dal (cooked)' -- the plan
    builder computes every nutrient from whichever entry wins."""
    context = [
        {"id": "FOOD_040", "food": "masoor dal (cooked)", "calories": 165},
        {"id": "FOOD_012", "food": "dal", "calories": 230},
    ]
    assert find_food("dal", context)["id"] == "FOOD_012"
    assert find_food("Masoor Dal", context)["id"] == "FOOD_040"
    assert find_food("unicorn", context) is None
