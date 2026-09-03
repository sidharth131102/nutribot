"""Runs a golden case through the real agent pipeline without touching MongoDB.

Reuses the exact node functions and routing predicates production uses
(backend/agents/*) so the harness evaluates real behavior, not a re-implementation.
"""
from backend.agents.calorie_agent import calorie_agent_node
from backend.agents.food_agent import food_agent_node
from backend.agents.graph import _route_after_calorie, _route_after_intent, _route_after_rag
from backend.agents.intent_agent import intent_agent_node
from backend.agents.meal_plan_agent import meal_plan_agent_node
from backend.agents.profile_agent import _format_profile_context
from backend.agents.rag_agent import rag_agent_node
from backend.agents.state import NutriBotState
from backend.eval.models import GoldenCase


async def run_case(case: GoldenCase) -> NutriBotState:
    profile = case.profile
    profile_context = _format_profile_context(profile, case.previous_plans)

    state: NutriBotState = {
        "user_id": f"eval-{case.id}",
        "session_id": f"eval-{case.id}",
        "user_message": case.user_message,
        "user_profile": profile,
        "profile_context": profile_context,
        "bot_name": profile.get("bot_name", "Nova"),
        "user_name": (profile.get("full_name") or "").split()[0] or "there",
        "chat_history": case.chat_history,
        "previous_plans": case.previous_plans,
    }

    state = await intent_agent_node(state)

    next_node = _route_after_intent(state)
    if next_node == "calorie":
        state = await calorie_agent_node(state)
        next_node = _route_after_calorie(state)
    if next_node == "rag":
        state = await rag_agent_node(state)
        next_node = _route_after_rag(state)
    if next_node == "food":
        state = await food_agent_node(state)

    state = await meal_plan_agent_node(state)
    return state
