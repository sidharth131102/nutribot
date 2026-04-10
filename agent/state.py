from typing import Any, TypedDict

from backend.schemas import CagContext, MealPlan, NutritionTargets, UserProfile


class NutriBotState(TypedDict, total=False):
    profile: UserProfile
    query: str
    targets: NutritionTargets
    cag_context: CagContext
    rag_docs: list[str]
    raw_generation: str
    plan: MealPlan
    validation_errors: list[str]
    attempts: int
    error: str
    allowed_foods: list[dict[str, Any]]
