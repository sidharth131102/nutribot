"""Agent 5 — Food DB Context Agent.

Filters food_db.json based on the user's diet type, allergens, medical
conditions, and glycemic index requirements, then formats the result for
the Meal Plan Generator.
"""
import logging

from backend.agents.state import NutriBotState
from backend.utils.food_filter import format_food_context, get_filtered_foods

logger = logging.getLogger("nutribot.agent.food")


async def food_agent_node(state: NutriBotState) -> NutriBotState:
    profile = state.get("user_profile", {})

    try:
        foods = get_filtered_foods(profile, limit=10)
        food_context_str = format_food_context(foods)
        logger.info("Food filter: %d approved items for user %s", len(foods), state.get("user_id"))
    except Exception as exc:
        logger.exception("Food filtering failed: %s", exc)
        foods = []
        food_context_str = "Food database temporarily unavailable."

    return {
        **state,
        "food_context": foods,
        "food_context_str": food_context_str,
    }
