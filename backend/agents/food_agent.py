"""Agent 5 — Food DB Context Agent.

Filters food_db.json based on the user's diet type, allergens, medical
conditions, and glycemic index requirements, then formats the result for
the Meal Plan Generator.
"""
import logging

from backend.agents.state import NutriBotState
from backend.utils.food_filter import format_food_context, get_filtered_foods, wants_cheat_day_in_conversation

logger = logging.getLogger("nutribot.agent.food")

FOOD_LIST_SIZE = 40


async def food_agent_node(state: NutriBotState) -> NutriBotState:
    profile = state.get("user_profile", {})
    include_treats = wants_cheat_day_in_conversation(state.get("user_message", ""), state.get("chat_history"))

    try:
        # 10 was tuned to stay under Groq's 8000 TPM ceiling, then 20 on Azure.
        # 20 still starved the breakfast/snack slots (see get_filtered_foods);
        # 40 costs ~1,200 prompt tokens, which Azure's quota doesn't notice.
        foods = get_filtered_foods(profile, limit=FOOD_LIST_SIZE, include_treats=include_treats)
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
