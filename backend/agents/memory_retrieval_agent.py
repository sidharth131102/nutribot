"""Memory Retrieval Agent (v2 roadmap Phase 3, read path).

Fetches this user's relevant long-term memory facts and recent episodic
events into state, ahead of generation. Pure DB reads -- no LLM call, so
no rate-limit/token-budget cost, and runs unconditionally (unlike memory
extraction, which is gated -- see backend/memory/extraction.py).
"""
import logging

from backend.agents.state import NutriBotState
from backend.db.mongo import UserScopedRepo, get_db

logger = logging.getLogger("nutribot.agent.memory_retrieval")


async def memory_retrieval_agent_node(state: NutriBotState) -> NutriBotState:
    user_id = state["user_id"]
    repo = UserScopedRepo(get_db(), user_id)

    try:
        relevant_memories = await repo.get_active_memories(limit=3)
        recent_events = await repo.get_recent_events(limit=2)
    except Exception:
        logger.exception("Memory retrieval failed for user_id=%s", user_id)
        relevant_memories, recent_events = [], []

    return {
        **state,
        "relevant_memories": relevant_memories,
        "recent_events": recent_events,
    }
