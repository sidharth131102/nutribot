"""Mifflin-St Jeor BMR + TDEE calorie calculator tool."""
from typing import Any

from langchain_core.tools import tool

from backend.models.user import ActivityLevel, Gender, Goal

ACTIVITY_MULTIPLIERS: dict[str, float] = {
    ActivityLevel.sedentary: 1.2,
    ActivityLevel.lightly_active: 1.375,
    ActivityLevel.moderately_active: 1.55,
    ActivityLevel.very_active: 1.725,
    ActivityLevel.extremely_active: 1.9,
}

GOAL_ADJUSTMENTS: dict[str, tuple[int, int]] = {
    # (min_adjustment, max_adjustment) in kcal
    Goal.fat_loss: (-500, -300),
    Goal.weight_gain: (250, 400),
    Goal.muscle_gain: (250, 400),
    Goal.maintenance: (0, 0),
    Goal.manage_medical: (0, 0),  # condition-specific, no generic adjustment
}

# Default macro split: Protein 30% / Carbs 40% / Fat 30%
DEFAULT_MACRO_SPLIT = {"protein": 0.30, "carbs": 0.40, "fat": 0.30}


def _compute_calories(profile: dict[str, Any]) -> dict[str, float]:
    weight = float(profile["weight_kg"])
    height = float(profile["height_cm"])
    age = int(profile["age"])
    gender = profile["gender"]
    activity = profile["activity_level"]
    goal = profile["goal"]

    # BMR — Mifflin-St Jeor
    gender_constant = 5 if gender == Gender.male else -161
    bmr = 10 * weight + 6.25 * height - 5 * age + gender_constant

    # TDEE
    multiplier = ACTIVITY_MULTIPLIERS.get(activity, 1.55)
    tdee = bmr * multiplier

    # Goal adjustment (use midpoint of range)
    adj_range = GOAL_ADJUSTMENTS.get(goal, (0, 0))
    adjustment = (adj_range[0] + adj_range[1]) / 2
    goal_calories = tdee + adjustment

    # Macros from goal_calories
    protein_g = round((goal_calories * DEFAULT_MACRO_SPLIT["protein"]) / 4, 1)
    carbs_g = round((goal_calories * DEFAULT_MACRO_SPLIT["carbs"]) / 4, 1)
    fat_g = round((goal_calories * DEFAULT_MACRO_SPLIT["fat"]) / 9, 1)
    # Condition-specific adjustments for PCOS / diabetes (lower carb)
    conditions = [c.lower() for c in profile.get("medical_conditions", [])]
    if "diabetes" in conditions or "pcos" in conditions:
        # Shift 10% of energy from carbs to protein
        protein_g = round((goal_calories * 0.35) / 4, 1)
        carbs_g = round((goal_calories * 0.30) / 4, 1)
        fat_g = round((goal_calories * 0.35) / 9, 1)

    return {
        "bmr": round(bmr, 1),
        "maintenance_calories": round(tdee, 1),
        "goal_calories": round(goal_calories, 1),
        "protein_g": protein_g,
        "carbs_g": carbs_g,
        "fat_g": fat_g,
        "fiber_g": 30.0,  # Standard recommendation
    }


@tool
def calculate_calories(profile_json: str) -> str:
    """Calculate BMR, TDEE, and macro targets for a user profile.

    Args:
        profile_json: JSON string of the user profile dict.

    Returns:
        JSON string with calorie and macro targets.
    """
    import json

    profile = json.loads(profile_json)
    result = _compute_calories(profile)
    return json.dumps(result)


def compute_calories(profile: dict[str, Any]) -> dict[str, float]:
    """Direct Python call (non-tool version) used internally by agents."""
    return _compute_calories(profile)
