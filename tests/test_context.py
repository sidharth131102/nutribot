from agent.context import build_cag_context
from backend.schemas import ActivityLevel, DietType, Gender, Goal, NutritionTargets, UserProfile


def test_cag_context_contains_required_sections():
    profile = UserProfile(
        age=35,
        gender=Gender.male,
        weight=75,
        height=172,
        activity_level=ActivityLevel.active,
        goal=Goal.lean_bulk,
        diet_type=DietType.veg,
        medical_conditions=["thyroid"],
        allergies=["soy"],
        food_preferences=["indian"],
        region="indian",
    )
    targets = NutritionTargets(bmr=1600, tdee=2500, target_calories=2700, protein_target=135)

    context = build_cag_context(profile, targets)

    assert context.targets == {"calories": 2700, "protein": 135}
    assert context.constraints["fat_percentage_range"] == [20, 35]
    assert context.restrictions["medical_conditions"] == ["thyroid"]
    assert context.region == "indian"
    assert context.allowed_foods
    assert all("food" in food for food in context.allowed_foods)
