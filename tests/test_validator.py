from backend.schemas import (
    ActivityLevel,
    DailyTotals,
    DietType,
    Gender,
    Goal,
    Meal,
    MealItem,
    MealPlan,
    NutritionTargets,
    UserProfile,
)
from tools.validator import validate_plan


def test_validator_rejects_invalid_food_and_allergy():
    profile = UserProfile(
        age=30,
        gender=Gender.female,
        weight=65,
        height=165,
        activity_level=ActivityLevel.light,
        goal=Goal.maintenance,
        diet_type=DietType.vegan,
        medical_conditions=[],
        allergies=["milk"],
    )
    targets = NutritionTargets(bmr=1400, tdee=1900, target_calories=1900, protein_target=117)
    plan = MealPlan(
        meals=[
            Meal(
                name="Breakfast",
                items=[
                    MealItem(food="paneer", quantity="100 grams", calories=265, protein=18, carbs=3, fat=20),
                    MealItem(food="moon cheese", quantity="50 grams", calories=300, protein=5, carbs=8, fat=10),
                ],
                total_calories=565,
            )
        ],
        daily_totals=DailyTotals(calories=565, protein=23, carbs=11, fat=30),
    )

    errors = validate_plan(plan, targets, profile)

    assert any("invalid food" in error for error in errors)
    assert any("violates diet type" in error for error in errors)
    assert any("violates allergy" in error for error in errors)
