from backend.schemas import ActivityLevel, DietType, Gender, Goal, UserProfile
from tools.calculator import calculate_targets


def test_calculate_targets_uses_mifflin_st_jeor_and_goal_adjustment():
    profile = UserProfile(
        age=30,
        gender=Gender.male,
        weight=80,
        height=180,
        activity_level=ActivityLevel.moderate,
        goal=Goal.fat_loss,
        diet_type=DietType.non_veg,
        medical_conditions=[],
    )

    targets = calculate_targets(profile)

    assert targets.bmr == 1780
    assert targets.tdee == 2759
    assert targets.target_calories == 2359
    assert targets.protein_target == 144
