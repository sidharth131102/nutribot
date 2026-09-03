"""Filter food_db.json items based on user profile constraints."""
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Literal

from backend.config import get_settings
from backend.models.user import DietType

# Mirrors backend/tools/calorie_tool.py's DEFAULT_MACRO_SPLIT — the food list
# offered to the model should span the same macro balance its targets assume,
# not skew to one macro and cap how many calories a plan can physically reach.
MACRO_SELECTION_SPLIT: dict[str, float] = {"protein": 0.30, "carb": 0.40, "fat": 0.30}

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


def _dominant_macro(food: dict[str, Any]) -> Literal["protein", "carb", "fat"]:
    """Classify a food by which macro contributes the most calories."""
    protein_cal = float(food.get("protein", 0)) * 4
    carb_cal = float(food.get("carbs", 0)) * 4
    fat_cal = float(food.get("fat", 0)) * 9
    top = max(protein_cal, carb_cal, fat_cal)
    if top == protein_cal:
        return "protein"
    if top == carb_cal:
        return "carb"
    return "fat"


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

    # Rank within a macro category: low GI first for relevant conditions, then high protein
    def _rank(food: dict[str, Any]) -> tuple:
        protein_score = -float(food.get("protein", 0))
        gi_score = 0 if food.get("glycemic_index") in LOW_GI_VALUES else 1
        return (gi_score, protein_score)

    # Select across protein/carb/fat pools proportionally to MACRO_SELECTION_SPLIT
    # instead of one flat protein-first sort — a pure protein-first ranking
    # systematically excludes carb/fat foods from a small `limit`, capping how
    # many calories a plan built only from these items can ever reach.
    pools: dict[str, list[dict[str, Any]]] = {"protein": [], "carb": [], "fat": []}
    for food in filtered:
        pools[_dominant_macro(food)].append(food)
    for pool in pools.values():
        pool.sort(key=_rank)

    allocation = {k: round(limit * v) for k, v in MACRO_SELECTION_SPLIT.items()}
    # Rounding may over/under-shoot `limit` by a food or two — fine, the
    # shortfall-redistribution pass below reconciles it against real pool sizes.

    selected: list[dict[str, Any]] = []
    remaining_pools = dict(pools)
    remaining_slots = limit
    categories = list(allocation.keys())
    for i, category in enumerate(categories):
        pool = remaining_pools[category]
        is_last = i == len(categories) - 1
        take = min(len(pool), remaining_slots) if is_last else min(len(pool), allocation[category])
        selected.extend(pool[:take])
        remaining_pools[category] = pool[take:]
        remaining_slots -= take

    # Redistribute any shortfall (a pool ran out) using whatever's left, in rank order
    if remaining_slots > 0:
        leftover = sorted(
            (food for pool in remaining_pools.values() for food in pool),
            key=_rank,
        )
        selected.extend(leftover[:remaining_slots])

    return selected[:limit]


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


_PAREN_SUFFIX = re.compile(r"\s*\([^)]*\)")


def _strip_qualifier(name: str) -> str:
    """'turkey breast (cooked)' -> 'turkey breast' — for tolerant name matching."""
    return _PAREN_SUFFIX.sub("", name).strip().lower()


def food_name_matches(candidate: str, food_context: list[dict[str, Any]]) -> bool:
    """Whether a model-generated food name reasonably matches an approved food.

    Tolerant on purpose: the model may drop a parenthetical qualifier or phrase
    a name slightly differently while still meaning an approved item. Used both
    to enforce the allow-list in production (meal_plan_agent._sanitize_plan) and
    to score it in the eval harness — kept in one place so they can't drift.
    """
    candidate_norm = _strip_qualifier(candidate)
    candidate_id = candidate.strip().lower()
    if not candidate_norm:
        return False

    for food in food_context:
        allowed_norm = _strip_qualifier(food.get("food", ""))
        allowed_id = str(food.get("id", "")).strip().lower()
        if not allowed_norm:
            continue
        if candidate_norm == allowed_norm or candidate_id == allowed_id:
            return True
        if candidate_norm in allowed_norm or allowed_norm in candidate_norm:
            return True

    return False
