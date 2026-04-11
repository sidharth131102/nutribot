"""Agent 3 — Calorie Calculator Agent (Tool-Calling).

Triggered for CALORIE_CALCULATION and MEAL_PLAN_REQUEST intents.
Calls the calculate_calories tool to compute BMR, TDEE, and macro targets.
"""
import logging

from backend.agents.state import NutriBotState
from backend.tools.calorie_tool import compute_calories

logger = logging.getLogger("nutribot.agent.calorie")


async def calorie_agent_node(state: NutriBotState) -> NutriBotState:
    profile = state.get("user_profile", {})
    if not profile:
        logger.error("No user profile in state for calorie calculation")
        return {**state, "calorie_result": {}}

    try:
        result = compute_calories(profile)
        logger.info(
            "Calorie calc — goal: %.0f kcal | P: %.0fg | C: %.0fg | F: %.0fg",
            result["goal_calories"],
            result["protein_g"],
            result["carbs_g"],
            result["fat_g"],
        )
    except Exception as exc:
        logger.exception("Calorie calculation failed: %s", exc)
        result = {}

    return {**state, "calorie_result": result}
