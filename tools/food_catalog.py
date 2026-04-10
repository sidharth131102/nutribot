import json
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from backend.config import get_settings
from backend.schemas import DietType, FoodDbItem, UserProfile


def _normal_conditions(conditions: Iterable[str]) -> set[str]:
    normalized = {condition.strip().lower().replace("_", " ") for condition in conditions}
    if "kidney disease" in normalized or "ckd" in normalized:
        normalized.add("kidney")
    return normalized


@lru_cache
def load_food_db(path: str | None = None) -> tuple[FoodDbItem, ...]:
    db_path = Path(path or get_settings().food_db_path)
    with db_path.open("r", encoding="utf-8") as file:
        raw_foods = json.load(file)
    return tuple(FoodDbItem.model_validate(food) for food in raw_foods)


def cond_safe(food: FoodDbItem, medical_conditions: Iterable[str]) -> bool:
    conditions = _normal_conditions(medical_conditions)
    tags = set(food.medical_tags)

    if "diabetes" in conditions:
        if food.glycemic_index not in {"low", "very_low"} and "diabetes_safe" not in tags:
            return False

    if "hypertension" in conditions or "high blood pressure" in conditions:
        if "high_sodium" in tags or "hypertension_avoid" in tags:
            return False

    if "kidney" in conditions:
        if "kidney_avoid" in tags:
            return False
        if food.protein > 25 and "controlled_protein" not in tags:
            return False

    return True


def get_allowed_foods(
    user_profile: UserProfile,
    food_db: Iterable[FoodDbItem] | None = None,
    limit: int = 100,
) -> list[FoodDbItem]:
    foods = list(food_db or load_food_db())
    allergies = set(user_profile.allergies)
    preferences = set(user_profile.food_preferences)
    region = user_profile.region

    filtered = [
        food
        for food in foods
        if user_profile.diet_type in food.diet_types
        and not allergies.intersection(food.allergens)
        and cond_safe(food, user_profile.medical_conditions)
    ]

    def rank(food: FoodDbItem) -> tuple[int, float, str]:
        region_score = 0
        if region and region in food.regions:
            region_score += 4
        region_score += len(preferences.intersection(food.tags))
        region_score += len(preferences.intersection(food.regions))
        region_score += 1 if "high_protein" in food.tags else 0
        return (-region_score, -food.protein, food.food)

    return sorted(filtered, key=rank)[:limit]


def allowed_foods_for_prompt(foods: Iterable[FoodDbItem]) -> list[dict[str, object]]:
    return [
        {
            "id": food.id,
            "food": food.food,
            "quantity_grams": food.quantity_grams,
            "calories": food.calories,
            "protein": food.protein,
            "carbs": food.carbs,
            "fat": food.fat,
            "meal_types": food.meal_types,
            "glycemic_index": food.glycemic_index,
            "medical_tags": food.medical_tags,
            "tags": food.tags,
        }
        for food in foods
    ]


def food_db_by_name(food_db: Iterable[FoodDbItem] | None = None) -> dict[str, FoodDbItem]:
    return {food.food.lower(): food for food in food_db or load_food_db()}
