from backend.schemas import MealPlan, NutritionTargets, UserProfile
from tools.food_catalog import food_db_by_name, get_allowed_foods


def _quantity_label(quantity_grams: float) -> str:
    value = int(quantity_grams) if quantity_grams.is_integer() else quantity_grams
    return f"{value} grams"


def validate_foods(plan: MealPlan) -> bool:
    valid_food_names = set(food_db_by_name())
    return all(
        item.food.lower() in valid_food_names
        for meal in plan.meals
        for item in meal.items
    )


def validate_plan(plan: MealPlan, targets: NutritionTargets, profile: UserProfile) -> list[str]:
    errors: list[str] = []
    totals = plan.daily_totals

    if abs(totals.calories - targets.target_calories) > 50:
        errors.append(
            f"calories out of range: {totals.calories} vs target {targets.target_calories}"
        )

    if totals.protein < targets.protein_target:
        errors.append(f"protein below target: {totals.protein} < {targets.protein_target}")

    macro_calories = totals.protein * 4 + totals.carbs * 4 + totals.fat * 9
    if abs(macro_calories - totals.calories) > 75:
        errors.append(
            f"macro calories inconsistent: {macro_calories:.1f} vs {totals.calories}"
        )

    fat_percentage = (totals.fat * 9 / totals.calories) * 100 if totals.calories else 0
    if not 20 <= fat_percentage <= 35:
        errors.append(f"fat percentage out of range: {fat_percentage:.1f}%")

    food_db = food_db_by_name()
    allowed_names = {food.food.lower() for food in get_allowed_foods(profile)}
    recomputed = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}

    for meal in plan.meals:
        meal_calories = 0.0
        for item in meal.items:
            catalog_item = food_db.get(item.food.lower())
            if catalog_item is None:
                errors.append(f"invalid food: {item.food}")
                continue

            if item.food.lower() not in allowed_names:
                errors.append(f"{item.food} is not in allowed_foods for this user")
            if profile.diet_type not in catalog_item.diet_types:
                errors.append(f"{item.food} violates diet type {profile.diet_type}")
            if set(profile.allergies).intersection(catalog_item.allergens):
                errors.append(f"{item.food} violates allergy restrictions")

            expected_quantity = _quantity_label(catalog_item.quantity_grams)
            if item.quantity != expected_quantity:
                errors.append(f"{item.food} quantity must be {expected_quantity}")

            meal_calories += catalog_item.calories
            recomputed["calories"] += catalog_item.calories
            recomputed["protein"] += catalog_item.protein
            recomputed["carbs"] += catalog_item.carbs
            recomputed["fat"] += catalog_item.fat

            for field in ("calories", "protein", "carbs", "fat"):
                expected = getattr(catalog_item, field)
                actual = getattr(item, field)
                if abs(expected - actual) > 0.2:
                    errors.append(f"{item.food} {field} must use food_db value {expected}")

        if abs(meal_calories - meal.total_calories) > 10:
            errors.append(f"{meal.name} total does not match item calories")

    for field, recomputed_value in recomputed.items():
        actual = getattr(totals, field)
        if abs(recomputed_value - actual) > 10:
            errors.append(
                f"daily {field} does not match food_db recomputation: {actual} vs {recomputed_value:.1f}"
            )

    return errors
