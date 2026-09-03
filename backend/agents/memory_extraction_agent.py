"""Memory Extraction Agent (v2 roadmap Phase 3, write path).

Runs conditionally after meal_plan -- only when
backend.memory.extraction.should_attempt_extraction() gates it in (see
backend/agents/graph.py's routing). Not every turn: a real LLM call per
message would add a 3rd Groq call on top of the already-fragile rate
budget (see docs/CURRENT_STATE.md).
"""
import logging

from backend.agents.state import NutriBotState
from backend.db.mongo import UserScopedRepo, get_db
from backend.memory.extraction import extract_memory_fact

logger = logging.getLogger("nutribot.agent.memory_extraction")


async def memory_extraction_agent_node(state: NutriBotState) -> NutriBotState:
    user_id = state["user_id"]
    user_message = state.get("user_message", "")
    response = state.get("response", "")

    try:
        extracted = await extract_memory_fact(user_message, response)
        if extracted and extracted.fact:
            repo = UserScopedRepo(get_db(), user_id)
            await repo.add_memory_fact(
                fact=extracted.fact,
                category=extracted.category or "preference",
                confidence=extracted.confidence,
            )
            logger.info("Extracted memory fact for user_id=%s: %s", user_id, extracted.fact)
    except Exception:
        logger.exception("Memory extraction failed for user_id=%s", user_id)

    return state
