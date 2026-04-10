from backend.schemas import ActivityLevel, DietType, Gender, Goal, UserProfile
from tools.food_catalog import get_allowed_foods, load_food_db


def test_allowed_foods_use_json_db_and_filter_allergies_and_conditions():
    profile = UserProfile(
        age=42,
        gender=Gender.female,
        weight=70,
        height=165,
        activity_level=ActivityLevel.light,
        goal=Goal.fat_loss,
        diet_type=DietType.veg,
        medical_conditions=["diabetes"],
        allergies=["milk"],
        region="indian",
    )

    foods = get_allowed_foods(profile, load_food_db())
    names = {food.food for food in foods}

    assert "paneer" not in names
    assert "banana" not in names
    assert "dal" in names
    assert all(profile.diet_type in food.diet_types for food in foods)
