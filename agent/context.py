from backend.schemas import CagContext, NutritionTargets, UserProfile
from tools.food_catalog import allowed_foods_for_prompt, get_allowed_foods


def build_cag_context(profile: UserProfile, targets: NutritionTargets) -> CagContext:
    allowed_foods = allowed_foods_for_prompt(get_allowed_foods(profile, limit=100))
    return CagContext(
        user_profile=profile,
        targets={
            "calories": targets.target_calories,
            "protein": targets.protein_target,
        },
        constraints={
            "fat_percentage_range": [20, 35],
            "meals": "3-5",
        },
        restrictions={
            "allergies": profile.allergies,
            "medical_conditions": profile.medical_conditions,
        },
        preferences=profile.food_preferences,
        allowed_foods=allowed_foods,
        region=profile.region,
    )
