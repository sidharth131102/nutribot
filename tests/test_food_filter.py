"""Tests for backend/utils/food_filter.py.

Allergen/diet exclusion is the most safety-critical test in the repo per the
v2 roadmap — a bug here could serve an allergen to an allergic user.
"""
from backend.utils.food_filter import food_name_matches, get_filtered_foods


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
