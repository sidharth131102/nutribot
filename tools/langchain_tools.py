from langchain_core.tools import tool

from backend.schemas import UserProfile
from tools.calculator import calculate_targets


@tool("calculate_nutrition_targets")
def calculate_nutrition_targets_tool(profile: UserProfile) -> dict[str, float]:
    """Deterministically calculate BMR, TDEE, calories, and protein from a profile."""
    return calculate_targets(profile).model_dump()
