"""Tests for backend/tools/calorie_tool.py.

Safety-critical per the v2 roadmap invariant #1: the LLM never does
deterministic math — this tool is the sole source of truth for it.
"""
import pytest

from backend.tools.calorie_tool import compute_calories

BASE_PROFILE = {
    "weight_kg": 70,
    "height_cm": 175,
    "age": 30,
    "gender": "male",
    "activity_level": "moderately_active",
    "goal": "maintenance",
    "medical_conditions": [],
}


def _bmr(weight, height, age, gender_constant):
    return 10 * weight + 6.25 * height - 5 * age + gender_constant


def test_bmr_male_gender_constant():
    result = compute_calories(BASE_PROFILE)
    assert result["bmr"] == round(_bmr(70, 175, 30, 5), 1)


def test_bmr_female_gender_constant():
    profile = {**BASE_PROFILE, "gender": "female"}
    result = compute_calories(profile)
    assert result["bmr"] == round(_bmr(70, 175, 30, -161), 1)


def test_bmr_other_gender_uses_non_male_constant():
    profile = {**BASE_PROFILE, "gender": "other"}
    result = compute_calories(profile)
    assert result["bmr"] == round(_bmr(70, 175, 30, -161), 1)


@pytest.mark.parametrize(
    "activity,multiplier",
    [
        ("sedentary", 1.2),
        ("lightly_active", 1.375),
        ("moderately_active", 1.55),
        ("very_active", 1.725),
        ("extremely_active", 1.9),
    ],
)
def test_activity_multipliers(activity, multiplier):
    profile = {**BASE_PROFILE, "activity_level": activity}
    result = compute_calories(profile)
    expected = _bmr(70, 175, 30, 5) * multiplier
    assert result["maintenance_calories"] == round(expected, 1)


@pytest.mark.parametrize(
    "goal,expected_adjustment",
    [
        ("fat_loss", -400),  # midpoint of (-500, -300)
        ("weight_gain", 325),  # midpoint of (250, 400)
        ("muscle_gain", 325),
        ("maintenance", 0),
        ("manage_medical", 0),
    ],
)
def test_goal_adjustments(goal, expected_adjustment):
    profile = {**BASE_PROFILE, "goal": goal}
    result = compute_calories(profile)
    tdee = _bmr(70, 175, 30, 5) * 1.55  # moderately_active
    assert result["goal_calories"] == round(tdee + expected_adjustment, 1)


def test_default_macro_split_no_conditions():
    result = compute_calories(BASE_PROFILE)
    goal_calories = result["goal_calories"]
    assert result["protein_g"] == round((goal_calories * 0.30) / 4, 1)
    assert result["carbs_g"] == round((goal_calories * 0.40) / 4, 1)
    assert result["fat_g"] == round((goal_calories * 0.30) / 9, 1)


@pytest.mark.parametrize(
    "conditions",
    [
        ["diabetes"],
        ["pcos"],
        ["diabetes", "pcos"],  # both present -- override applies once, not stacked
    ],
)
def test_diabetes_pcos_macro_override(conditions):
    profile = {**BASE_PROFILE, "medical_conditions": conditions}
    result = compute_calories(profile)
    goal_calories = result["goal_calories"]
    assert result["protein_g"] == round((goal_calories * 0.35) / 4, 1)
    assert result["carbs_g"] == round((goal_calories * 0.30) / 4, 1)
    assert result["fat_g"] == round((goal_calories * 0.35) / 9, 1)


def test_condition_matching_is_case_insensitive():
    profile = {**BASE_PROFILE, "medical_conditions": ["Diabetes"]}
    result = compute_calories(profile)
    goal_calories = result["goal_calories"]
    assert result["protein_g"] == round((goal_calories * 0.35) / 4, 1)


def test_fiber_is_constant():
    assert compute_calories(BASE_PROFILE)["fiber_g"] == 30.0


def test_unrecognized_activity_level_falls_back_to_moderate():
    profile = {**BASE_PROFILE, "activity_level": "not_a_real_level"}
    result = compute_calories(profile)
    assert result["maintenance_calories"] == round(_bmr(70, 175, 30, 5) * 1.55, 1)


def test_unrecognized_goal_has_no_adjustment():
    profile = {**BASE_PROFILE, "goal": "not_a_real_goal"}
    result = compute_calories(profile)
    assert result["goal_calories"] == round(_bmr(70, 175, 30, 5) * 1.55, 1)
