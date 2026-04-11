"""Filter food_db.json items based on user profile constraints."""
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from backend.config import get_settings
from backend.models.user import DietType

# Map spec DietType values → food_db.json diet_types values
DIET_TYPE_MAP: dict[str, str] = {
    DietType.vegetarian: "veg",
    DietType.vegan: "vegan",
    DietType.non_vegetarian: "non_veg",
}

# Conditions that require low GI foods
LOW_GI_CONDITIONS = {"diabetes", "pcos", "type 2 diabetes", "type2 diabetes"}

LOW_GI_VALUES = {"low", "very_low"}


@lru_cache(maxsize=1)
def _load_food_db() -> list[dict[str, Any]]:
    path = Path(get_settings().food_db_path)
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _normalize(values: Iterable[str]) -> set[str]:
    return {v.strip().lower().replace("-", " ").replace("_", " ") for v in values}


def _is_condition_safe(food: dict[str, Any], conditions: set[str]) -> bool:
    tags = set(food.get("medical_tags", []))
    gi = (food.get("glycemic_index") or "").lower()

    if "diabetes" in conditions or "type 2 diabetes" in conditions:
        if gi not in LOW_GI_VALUES and "diabetes_safe" not in tags:
            return False

    if "hypertension" in conditions or "high blood pressure" in conditions:
        if "high_sodium" in tags or "hypertension_avoid" in tags:
            return False

    if "kidney disease" in conditions or "ckd" in conditions or "kidney" in conditions:
        if "kidney_avoid" in tags:
            return False
        if float(food.get("protein", 0)) > 25 and "controlled_protein" not in tags:
            return False

    return True


def get_filtered_foods(
    user_profile: dict[str, Any],
    meal_type: str | None = None,
    limit: int = 80,
) -> list[dict[str, Any]]:
    """Return foods filtered and ranked for the given user profile.

    Args:
        user_profile: The full user profile dict.
        meal_type: Optional filter by meal type (breakfast/lunch/dinner/snack).
        limit: Maximum number of foods to return.

    Returns:
        List of food dicts from food_db.json that pass all filters.
    """
    foods = _load_food_db()
    diet_type_raw = user_profile.get("diet_type", "")
    diet_key = DIET_TYPE_MAP.get(diet_type_raw, diet_type_raw)

    allergies = _normalize(user_profile.get("allergies", []))
    conditions = _normalize(user_profile.get("medical_conditions", []))
    needs_low_gi = bool(LOW_GI_CONDITIONS.intersection(conditions))

    filtered: list[dict[str, Any]] = []
    for food in foods:
        # Diet type check
        food_diets = {d.lower() for d in food.get("diet_types", [])}
        if diet_key not in food_diets:
            continue

        # Allergen check (absolute)
        food_allergens = _normalize(food.get("allergens", []))
        if allergies.intersection(food_allergens):
            continue

        # Medical condition safety (absolute)
        if not _is_condition_safe(food, conditions):
            continue

        # Meal type filter (optional)
        if meal_type:
            food_meal_types = {m.lower() for m in food.get("meal_types", [])}
            if meal_type.lower() not in food_meal_types:
                continue

        # Low GI enforcement for diabetics/PCOS
        if needs_low_gi:
            gi = (food.get("glycemic_index") or "").lower()
            if gi and gi not in LOW_GI_VALUES and gi != "medium":
                continue

        filtered.append(food)

    # Rank: prefer high protein, then low GI for relevant conditions
    def _rank(food: dict[str, Any]) -> tuple:
        protein_score = -float(food.get("protein", 0))
        gi_score = 0 if food.get("glycemic_index") in LOW_GI_VALUES else 1
        return (gi_score, protein_score)

    filtered.sort(key=_rank)
    return filtered[:limit]


def format_food_context(foods: list[dict[str, Any]]) -> str:
    """Format filtered foods as a readable string for the LLM prompt."""
    if not foods:
        return "No approved foods available."
    lines = ["APPROVED FOOD OPTIONS (use ONLY these items):"]
    lines.append(
        f"{'ID':<10} {'Food':<35} {'g':>5} {'kcal':>6} {'P':>5} {'C':>5} {'F':>5} {'Meal Types'}"
    )
    lines.append("-" * 100)
    for f in foods:
        lines.append(
            f"{f['id']:<10} {f['food']:<35} {f['quantity_grams']:>5} "
            f"{f['calories']:>6} {f['protein']:>5} {f['carbs']:>5} {f['fat']:>5} "
            f"{', '.join(f.get('meal_types', []))}"
        )
    return "\n".join(lines)
