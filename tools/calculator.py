from backend.schemas import ActivityLevel, Gender, Goal, NutritionTargets, UserProfile


ACTIVITY_FACTORS: dict[ActivityLevel, float] = {
    ActivityLevel.sedentary: 1.2,
    ActivityLevel.light: 1.375,
    ActivityLevel.moderate: 1.55,
    ActivityLevel.active: 1.725,
    ActivityLevel.very_active: 1.9,
}

GOAL_ADJUSTMENTS: dict[Goal, int] = {
    Goal.fat_loss: -400,
    Goal.lean_loss: -200,
    Goal.maintenance: 0,
    Goal.lean_bulk: 200,
    Goal.bulk: 400,
}


def calculate_targets(profile: UserProfile) -> NutritionTargets:
    """Calculate BMR, TDEE, calories, and protein without any LLM involvement."""
    gender_constant = 5 if profile.gender == Gender.male else -161
    bmr = 10 * profile.weight + 6.25 * profile.height - 5 * profile.age + gender_constant
    tdee = bmr * ACTIVITY_FACTORS[profile.activity_level]
    target_calories = tdee + GOAL_ADJUSTMENTS[profile.goal]
    protein_target = profile.weight * 1.8

    return NutritionTargets(
        bmr=round(bmr, 2),
        tdee=round(tdee, 2),
        target_calories=round(target_calories, 2),
        protein_target=round(protein_target, 2),
    )
